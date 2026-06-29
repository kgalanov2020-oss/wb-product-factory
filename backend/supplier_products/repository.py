from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from supabase import Client, create_client

from backend.config import Settings

from .analysis import ANALYSIS_VERSION
from .exceptions import SupplierProductRepositoryError
from .models import (
    ProductAnalysis,
    ProductListResponse,
    SupplierProduct,
    SupplierProductInput,
    WBCardMappingInput,
    WBStockSnapshotInput,
)


def _repository_error(exc: Exception) -> SupplierProductRepositoryError:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > 500:
        message = f"{message[:500]}..."
    return SupplierProductRepositoryError(
        "Supplier product tables are unavailable. Apply supabase/schema.sql. "
        f"Supabase error: {message}"
    )


class SupplierProductRepository(Protocol):
    async def upsert_products(self, products: list[SupplierProductInput]) -> int: ...
    async def upsert_mappings(self, mappings: list[WBCardMappingInput]) -> int: ...
    async def upsert_stocks(self, stocks: list[WBStockSnapshotInput]) -> int: ...
    async def refresh_product_statuses(self, supplier: str) -> None: ...
    async def product_stats(self) -> dict[str, int]: ...

    async def list_products(self, limit: int, offset: int, status: str | None) -> ProductListResponse: ...

    async def get_product(self, product_id: UUID) -> SupplierProduct | None: ...

    async def get_analysis(self, product_id: UUID) -> ProductAnalysis | None: ...

    async def save_analysis(self, analysis: ProductAnalysis) -> None: ...

    async def list_recommended_products(self, limit: int, min_score: float) -> list[SupplierProduct]: ...

    async def update_product_photos(self, product_id: UUID, photo_urls: list[str]) -> None: ...

    async def update_product_status(self, product_id: UUID, status: str) -> None: ...


class NullSupplierProductRepository:
    async def upsert_products(self, products: list[SupplierProductInput]) -> int:
        return 0

    async def upsert_mappings(self, mappings: list[WBCardMappingInput]) -> int:
        return 0

    async def upsert_stocks(self, stocks: list[WBStockSnapshotInput]) -> int:
        return 0

    async def refresh_product_statuses(self, supplier: str) -> None:
        return None

    async def product_stats(self) -> dict[str, int]:
        return {"total": 0, "missing_on_wb": 0, "listed": 0, "analyzed": 0, "content_ready": 0}

    async def list_products(self, limit: int, offset: int, status: str | None) -> ProductListResponse:
        return ProductListResponse(products=[], total=0)

    async def get_product(self, product_id: UUID) -> SupplierProduct | None:
        return None

    async def get_analysis(self, product_id: UUID) -> ProductAnalysis | None:
        return None

    async def save_analysis(self, analysis: ProductAnalysis) -> None:
        return None

    async def list_recommended_products(self, limit: int, min_score: float) -> list[SupplierProduct]:
        return []

    async def update_product_photos(self, product_id: UUID, photo_urls: list[str]) -> None:
        return None

    async def update_product_status(self, product_id: UUID, status: str) -> None:
        return None


class SupabaseSupplierProductRepository:
    def __init__(
        self,
        client: Client,
        products_table: str,
        analyses_table: str,
        mappings_table: str,
        stocks_table: str,
    ) -> None:
        self._client = client
        self._products_table = products_table
        self._analyses_table = analyses_table
        self._mappings_table = mappings_table
        self._stocks_table = stocks_table

    @classmethod
    def from_settings(cls, settings: Settings) -> SupabaseSupplierProductRepository:
        if not settings.supabase_configured:
            raise ValueError("Supabase is not configured")
        key = settings.supabase_service_role_key
        assert settings.supabase_url is not None and key is not None
        client = create_client(str(settings.supabase_url), key.get_secret_value())
        return cls(
            client,
            settings.supabase_supplier_products_table,
            settings.supabase_product_analyses_table,
            settings.supabase_wb_card_mappings_table,
            settings.supabase_wb_stock_snapshots_table,
        )

    async def upsert_products(self, products: list[SupplierProductInput]) -> int:
        if not products:
            return 0
        payloads = [
            {
                "supplier": product.supplier,
                "sku": product.sku,
                "barcode": product.barcode,
                "name": product.name,
                "category": product.category,
                "wholesale_price": str(product.wholesale_price) if product.wholesale_price is not None else None,
                "retail_price": str(product.retail_price) if product.retail_price is not None else None,
                "stock": product.stock,
                "pack_units": product.pack_units,
                "weight_grams": str(product.weight_grams) if product.weight_grams is not None else None,
                "dimensions": product.dimensions,
                "description": product.description,
                "order_quantity": product.order_quantity,
                "photo_urls": [str(url) for url in product.photo_urls],
                "source_url": str(product.source_url) if product.source_url else None,
                "raw": product.raw,
            }
            for product in products
        ]
        try:
            await asyncio.to_thread(
                lambda: self._client.table(self._products_table)
                .upsert(payloads, on_conflict="supplier,sku")
                .execute()
            )
        except Exception as exc:
            raise _repository_error(exc) from exc
        return len(products)

    async def upsert_mappings(self, mappings: list[WBCardMappingInput]) -> int:
        if not mappings:
            return 0
        payloads = [
            {
                "mapping_key": _mapping_key(mapping),
                "supplier": mapping.supplier,
                "manufacturer_article": mapping.manufacturer_article,
                "seller_article": mapping.seller_article,
                "wb_article": mapping.wb_article,
                "barcode": mapping.barcode,
                "brand": mapping.brand,
                "subject": mapping.subject,
                "name": mapping.name,
                "purchase_price": str(mapping.purchase_price) if mapping.purchase_price is not None else None,
                "retail_price": str(mapping.retail_price) if mapping.retail_price is not None else None,
                "pack_units": mapping.pack_units,
                "raw": mapping.raw,
            }
            for mapping in mappings
        ]
        try:
            await asyncio.to_thread(
                lambda: self._client.table(self._mappings_table)
                .upsert(payloads, on_conflict="mapping_key")
                .execute()
            )
        except Exception as exc:
            raise _repository_error(exc) from exc
        return len(mappings)

    async def upsert_stocks(self, stocks: list[WBStockSnapshotInput]) -> int:
        if not stocks:
            return 0
        payloads = [
            {
                "wb_article": stock.wb_article,
                "seller_article": stock.seller_article,
                "brand": stock.brand,
                "subject": stock.subject,
                "stock_qty": stock.stock_qty,
                "in_way_to_client": stock.in_way_to_client,
                "in_way_from_client": stock.in_way_from_client,
                "raw": stock.raw,
            }
            for stock in stocks
        ]
        try:
            await asyncio.to_thread(lambda: self._client.table(self._stocks_table).insert(payloads).execute())
        except Exception as exc:
            raise _repository_error(exc) from exc
        return len(stocks)

    async def refresh_product_statuses(self, supplier: str) -> None:
        def refresh() -> None:
            self._client.rpc("refresh_supplier_product_statuses", {"supplier_arg": supplier}).execute()

        try:
            await asyncio.to_thread(refresh)
        except Exception as exc:
            raise _repository_error(exc) from exc

    async def product_stats(self) -> dict[str, int]:
        statuses = ("missing_on_wb", "listed", "analyzed", "content_ready")

        def count(status: str | None = None) -> int:
            query = self._client.table(self._products_table).select("id", count="exact")
            if status:
                query = query.eq("status", status)
            response = query.limit(1).execute()
            return response.count or 0

        try:
            return await asyncio.to_thread(
                lambda: {
                    "total": count(),
                    **{status: count(status) for status in statuses},
                }
            )
        except Exception as exc:
            raise _repository_error(exc) from exc

    async def list_products(self, limit: int, offset: int, status: str | None) -> ProductListResponse:
        def select() -> tuple[list[dict], int]:
            query = self._client.table(self._products_table).select("*", count="exact")
            if status:
                query = query.eq("status", status)
            response = query.order("updated_at", desc=True).range(offset, offset + limit - 1).execute()
            return response.data or [], response.count or 0

        try:
            rows, total = await asyncio.to_thread(select)
        except Exception as exc:
            raise _repository_error(exc) from exc
        return ProductListResponse(products=[_product_from_row(row) for row in rows], total=total)

    async def get_product(self, product_id: UUID) -> SupplierProduct | None:
        def select() -> dict | None:
            response = (
                self._client.table(self._products_table)
                .select("*")
                .eq("id", str(product_id))
                .maybe_single()
                .execute()
            )
            return response.data if response is not None else None

        try:
            row = await asyncio.to_thread(select)
        except Exception as exc:
            raise _repository_error(exc) from exc
        return _product_from_row(row) if row else None

    async def get_analysis(self, product_id: UUID) -> ProductAnalysis | None:
        def select() -> dict | None:
            response = (
                self._client.table(self._analyses_table)
                .select("*")
                .eq("product_id", str(product_id))
                .maybe_single()
                .execute()
            )
            return response.data if response is not None else None

        try:
            row = await asyncio.to_thread(select)
        except Exception as exc:
            raise _repository_error(exc) from exc
        return ProductAnalysis(**row) if row else None

    async def save_analysis(self, analysis: ProductAnalysis) -> None:
        payload = analysis.model_dump(mode="json")
        try:
            def save() -> None:
                self._client.table(self._analyses_table).upsert(payload).execute()
                update_payload = {"launch_score": analysis.launch_score}
                if analysis.status == "completed":
                    update_payload["status"] = "analyzed"
                elif analysis.status == "pending":
                    update_payload["status"] = "analysis_pending"
                self._client.table(self._products_table).update(update_payload).eq(
                    "id",
                    str(analysis.product_id),
                ).execute()

            await asyncio.to_thread(save)
        except Exception as exc:
            raise _repository_error(exc) from exc

    async def list_recommended_products(self, limit: int, min_score: float) -> list[SupplierProduct]:
        def select_analyzed() -> list[dict]:
            query = (
                self._client.table(self._analyses_table)
                .select("product_id,launch_score,raw,status")
                .eq("status", "completed")
                .contains("raw", {"analysis_version": ANALYSIS_VERSION})
                .order("launch_score", desc=True)
                .limit(max(limit * 5, 20))
            )
            if min_score > 0:
                query = query.gte("launch_score", min_score)
            response = query.execute()
            return response.data or []

        def select_products_by_ids(product_ids: list[str]) -> list[dict]:
            if not product_ids:
                return []
            response = (
                self._client.table(self._products_table)
                .select("*")
                .in_("id", product_ids)
                .execute()
            )
            rows = response.data or []
            order = {product_id: index for index, product_id in enumerate(product_ids)}
            return sorted(rows, key=lambda row: order.get(str(row.get("id")), len(order)))

        def select_fillers() -> list[dict]:
            query = (
                self._client.table(self._products_table)
                .select("*")
                .in_("status", ["missing_on_wb", "new"])
                .order("updated_at", desc=True)
                .limit(max(limit * 5, 20))
            )
            response = query.execute()
            return response.data or []

        try:
            analysis_rows = await asyncio.to_thread(select_analyzed)
            product_ids = [str(row["product_id"]) for row in analysis_rows if row.get("product_id")]
            rows = await asyncio.to_thread(lambda: select_products_by_ids(product_ids))
            if min_score <= 0 and len(rows) < limit:
                rows.extend(await asyncio.to_thread(select_fillers))
        except Exception as exc:
            raise _repository_error(exc) from exc
        products = [_product_from_row(row) for row in rows]
        return [
            product
            for product in products
            if product.sku
            and len(product.name.strip()) > 5
            and (product.source_url or product.photo_urls)
        ][:limit]

    async def update_product_photos(self, product_id: UUID, photo_urls: list[str]) -> None:
        try:
            await asyncio.to_thread(
                lambda: self._client.table(self._products_table)
                .update({"photo_urls": photo_urls})
                .eq("id", str(product_id))
                .execute()
            )
        except Exception as exc:
            raise _repository_error(exc) from exc

    async def update_product_status(self, product_id: UUID, status: str) -> None:
        try:
            await asyncio.to_thread(
                lambda: self._client.table(self._products_table)
                .update({"status": status})
                .eq("id", str(product_id))
                .execute()
            )
        except Exception as exc:
            raise _repository_error(exc) from exc


def _product_from_row(row: dict) -> SupplierProduct:
    return SupplierProduct(
        id=row["id"],
        supplier=row["supplier"],
        sku=row.get("sku"),
        barcode=row.get("barcode"),
        name=row["name"],
        category=row.get("category"),
        wholesale_price=row.get("wholesale_price"),
        retail_price=row.get("retail_price"),
        stock=row.get("stock"),
        pack_units=row.get("pack_units"),
        weight_grams=row.get("weight_grams"),
        dimensions=row.get("dimensions"),
        description=row.get("description"),
        order_quantity=row.get("order_quantity"),
        photo_urls=row.get("photo_urls") or [],
        source_url=row.get("source_url"),
        status=row.get("status") or "new",
        launch_score=row.get("launch_score"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _mapping_key(mapping: WBCardMappingInput) -> str:
    values = [
        mapping.supplier,
        mapping.manufacturer_article,
        mapping.seller_article,
        mapping.wb_article,
        mapping.barcode,
    ]
    return ":".join((value or "").strip().lower() for value in values)
