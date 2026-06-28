from __future__ import annotations

from uuid import UUID

import httpx

from backend.mpstats_collector.models import CollectionRequest
from backend.mpstats_collector.service import MPStatsCollectorService

from .analysis import build_market_analysis
from .exceptions import SupplierPriceListError
from .models import PriceListImportResult, ProductAnalysis, ProductListResponse, SupplierProduct
from .parser import parse_price_list
from .repository import SupplierProductRepository


class SupplierProductService:
    def __init__(
        self,
        repository: SupplierProductRepository,
        mpstats_service: MPStatsCollectorService | None = None,
    ) -> None:
        self._repository = repository
        self._mpstats_service = mpstats_service

    async def import_from_url(self, url: str, supplier: str) -> PriceListImportResult:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(url)
        if response.is_error:
            raise SupplierPriceListError(f"Price list download failed: {response.status_code}")
        content_type = response.headers.get("content-type", "")
        filename = "price.xlsx" if "spreadsheet" in content_type else "price.csv"
        products = parse_price_list(response.content, filename, supplier)
        imported = await self._repository.upsert_products(products)
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
        products = parse_price_list(content, filename, supplier)
        imported = await self._repository.upsert_products(products)
        return PriceListImportResult(
            supplier=supplier,
            imported=imported,
            skipped=max(len(products) - imported, 0),
            persisted=imported > 0,
        )

    async def list_products(self, limit: int, offset: int, status: str | None) -> ProductListResponse:
        return await self._repository.list_products(limit=limit, offset=offset, status=status)

    async def get_product(self, product_id: UUID) -> SupplierProduct | None:
        return await self._repository.get_product(product_id)

    async def analyze_product(self, product_id: UUID) -> ProductAnalysis | None:
        if self._mpstats_service is None:
            raise SupplierPriceListError("MPStats service is not configured")
        product = await self._repository.get_product(product_id)
        if product is None:
            return None
        snapshot = (await self._mpstats_service.collect(CollectionRequest(query=product.name))).collection
        analysis = build_market_analysis(product, snapshot)
        await self._repository.save_analysis(analysis)
        return analysis
