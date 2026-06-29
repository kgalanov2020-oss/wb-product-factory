from __future__ import annotations

from uuid import UUID

import httpx

from backend.mpstats_collector.service import MPStatsCollectorService
from backend.config import Settings

from .analysis import build_market_analysis
from .exceptions import SupplierPriceListError
from .mpstats_api import collect_mpstats_api_snapshot
from .models import (
    BatchAnalysisRequest,
    BatchAnalysisResult,
    PriceListImportResult,
    ProductAnalysis,
    ProductListResponse,
    ProductStatsResponse,
    SupplierProduct,
    ProductStatus,
    WorkbookImportResult,
)
from .parser import parse_price_list
from .repository import SupplierProductRepository
from .workbook import parse_zvezda_workbook


class SupplierProductService:
    def __init__(
        self,
        repository: SupplierProductRepository,
        mpstats_service: MPStatsCollectorService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._mpstats_service = mpstats_service
        self._settings = settings

    async def import_from_url(self, url: str, supplier: str) -> PriceListImportResult:
        url, filename = _normalize_price_list_url(url)
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(url)
        if response.is_error:
            raise SupplierPriceListError(f"Price list download failed: {response.status_code}")
        content_type = response.headers.get("content-type", "")
        if filename is None:
            filename = "price.xlsx" if "spreadsheet" in content_type else "price.csv"
        if filename.lower().endswith(".xlsx"):
            products, mappings, stocks = parse_zvezda_workbook(response.content, supplier)
            imported = await self._repository.upsert_products(products)
            await self._repository.upsert_mappings(mappings)
            await self._repository.upsert_stocks(stocks)
            await self._repository.refresh_product_statuses(supplier)
        else:
            products = parse_price_list(response.content, filename, supplier)
            imported = await self._repository.upsert_products(products)
            await self._repository.refresh_product_statuses(supplier)
        return PriceListImportResult(
            supplier=supplier,
            imported=imported,
            skipped=max(len(products) - imported, 0),
            persisted=imported > 0,
        )

    async def import_from_file(
        self,
        content: bytes,
        filename: str,
        supplier: str,
    ) -> PriceListImportResult:
        if filename.lower().endswith(".xlsx"):
            products, mappings, stocks = parse_zvezda_workbook(content, supplier)
            imported = await self._repository.upsert_products(products)
            await self._repository.upsert_mappings(mappings)
            await self._repository.upsert_stocks(stocks)
            await self._repository.refresh_product_statuses(supplier)
        else:
            products = parse_price_list(content, filename, supplier)
            imported = await self._repository.upsert_products(products)
            await self._repository.refresh_product_statuses(supplier)
        return PriceListImportResult(
            supplier=supplier,
            imported=imported,
            skipped=max(len(products) - imported, 0),
            persisted=imported > 0,
        )

    async def import_workbook_from_url(self, url: str, supplier: str) -> WorkbookImportResult:
        url, _filename = _normalize_price_list_url(url)
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(url)
        if response.is_error:
            raise SupplierPriceListError(f"Workbook download failed: {response.status_code}")
        products, mappings, stocks = parse_zvezda_workbook(response.content, supplier)
        products_imported = await self._repository.upsert_products(products)
        mappings_imported = await self._repository.upsert_mappings(mappings)
        stocks_imported = await self._repository.upsert_stocks(stocks)
        await self._repository.refresh_product_statuses(supplier)
        return WorkbookImportResult(
            supplier=supplier,
            products_imported=products_imported,
            mappings_imported=mappings_imported,
            stocks_imported=stocks_imported,
            persisted=products_imported > 0,
        )

    async def list_products(self, limit: int, offset: int, status: str | None) -> ProductListResponse:
        return await self._repository.list_products(limit=limit, offset=offset, status=status)

    async def product_stats(self) -> ProductStatsResponse:
        return ProductStatsResponse(**await self._repository.product_stats())

    async def get_product(self, product_id: UUID) -> SupplierProduct | None:
        return await self._repository.get_product(product_id)

    async def get_analysis(self, product_id: UUID) -> ProductAnalysis | None:
        return await self._repository.get_analysis(product_id)

    async def update_status(self, product_id: UUID, status: ProductStatus) -> SupplierProduct | None:
        product = await self._repository.get_product(product_id)
        if product is None:
            return None
        await self._repository.update_product_status(product_id, status)
        return await self._repository.get_product(product_id)

    async def analyze_product(self, product_id: UUID) -> ProductAnalysis | None:
        product = await self._repository.get_product(product_id)
        if product is None:
            return None
        return await self._analyze_loaded_product(product)

    async def analyze_batch(self, request: BatchAnalysisRequest) -> BatchAnalysisResult:
        candidates = await self._repository.list_analysis_candidates(
            limit=request.limit,
            supplier=request.supplier,
            include_rejected=request.include_rejected,
        )
        analyses: list[ProductAnalysis] = []
        with_data = 0
        without_data = 0
        errors = 0
        for product in candidates.products:
            analysis = await self._analyze_loaded_product(product)
            analyses.append(analysis)
            if analysis.status == "completed":
                with_data += 1
            elif analysis.status == "failed":
                without_data += 1
            else:
                errors += 1
        next_candidates = await self._repository.list_analysis_candidates(
            limit=1,
            supplier=request.supplier,
            include_rejected=request.include_rejected,
        )
        return BatchAnalysisResult(
            requested=len(candidates.products),
            analyzed=len(analyses),
            with_data=with_data,
            without_data=without_data,
            errors=errors,
            remaining=next_candidates.total,
            products=analyses,
        )

    async def _analyze_loaded_product(self, product: SupplierProduct) -> ProductAnalysis:
        if self._settings is not None and getattr(self._settings, "mpstats_api_configured", False):
            try:
                snapshot = await collect_mpstats_api_snapshot(
                    self._settings,
                    _mpstats_query(product),
                    product_name=product.name,
                    product_sku=product.sku,
                    reference_price=product.wholesale_price,
                )
            except httpx.HTTPStatusError as exc:
                analysis = ProductAnalysis(
                    product_id=product.id,
                    status="failed",
                    notes=f"MPStats API недоступен: HTTP {exc.response.status_code}. Проверьте MPSTATS_API_TOKEN.",
                    raw={"error": str(exc)},
                )
                await self._repository.save_analysis(analysis)
                return analysis
            except httpx.HTTPError as exc:
                analysis = ProductAnalysis(
                    product_id=product.id,
                    status="failed",
                    notes=f"MPStats API недоступен: {exc}",
                    raw={"error": str(exc)},
                )
                await self._repository.save_analysis(analysis)
                return analysis
        else:
            analysis = ProductAnalysis(
                product_id=product.id,
                status="failed",
                notes="Для анализа нужен MPSTATS_API_TOKEN в Render. Браузерный MPStats и WB public search не дают стабильные рыночные данные.",
                raw={"error": "MPSTATS_API_TOKEN is not configured"},
            )
            await self._repository.save_analysis(analysis)
            return analysis

        if snapshot is None or not snapshot.competitors:
            analysis = ProductAnalysis(
                product_id=product.id,
                status="failed",
                notes="MPStats API не вернул конкурентов по этому запросу.",
                raw={"error": "MPStats API returned no competitors"},
            )
            await self._repository.save_analysis(analysis)
            return analysis
        analysis = build_market_analysis(product, snapshot)
        await self._repository.save_analysis(analysis)
        return analysis


def _normalize_price_list_url(url: str) -> tuple[str, str | None]:
    if "docs.google.com/spreadsheets" not in url:
        return url, None
    marker = "/d/"
    if marker not in url:
        return url, None
    spreadsheet_id = url.split(marker, 1)[1].split("/", 1)[0]
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx",
        "price.xlsx",
    )


def _mpstats_query(product: SupplierProduct) -> str:
    parts = ["Звезда"]
    if product.sku:
        parts.append(product.sku)
    parts.append(product.name)
    return " ".join(part for part in parts if part).strip()[:300]
