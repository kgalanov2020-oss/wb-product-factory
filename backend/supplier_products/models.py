from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


ProductStatus = Literal[
    "new",
    "missing_on_wb",
    "listed",
    "analysis_pending",
    "analyzed",
    "content_pending",
    "content_ready",
    "rejected",
]


class SupplierProductInput(BaseModel):
    supplier: str = "zvezda"
    sku: str | None = Field(default=None, max_length=120)
    barcode: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=300)
    wholesale_price: Decimal | None = None
    retail_price: Decimal | None = None
    stock: int | None = None
    pack_units: int | None = None
    weight_grams: Decimal | None = None
    dimensions: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    order_quantity: int | None = None
    photo_urls: list[HttpUrl] = Field(default_factory=list)
    source_url: HttpUrl | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SupplierProduct(BaseModel):
    id: UUID
    supplier: str
    sku: str | None
    barcode: str | None
    name: str
    category: str | None
    wholesale_price: Decimal | None
    retail_price: Decimal | None
    stock: int | None
    pack_units: int | None = None
    weight_grams: Decimal | None = None
    dimensions: str | None = None
    description: str | None = None
    order_quantity: int | None = None
    photo_urls: list[str]
    source_url: str | None
    status: ProductStatus
    launch_score: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PriceListImportRequest(BaseModel):
    url: HttpUrl
    supplier: str = "zvezda"


class PriceListImportResult(BaseModel):
    supplier: str
    imported: int
    skipped: int
    persisted: bool


class ProductAnalysis(BaseModel):
    product_id: UUID
    status: Literal["pending", "completed", "failed"]
    market_price_min: Decimal | None = None
    market_price_avg: Decimal | None = None
    market_price_max: Decimal | None = None
    competitor_count: int | None = None
    estimated_sales: int | None = None
    estimated_revenue: Decimal | None = None
    margin_percent: float | None = None
    launch_score: float | None = None
    notes: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ProductListResponse(BaseModel):
    products: list[SupplierProduct]
    total: int


class ProductStatsResponse(BaseModel):
    total: int
    missing_on_wb: int
    listed: int
    analyzed: int
    content_ready: int


class WBCardMappingInput(BaseModel):
    supplier: str = "zvezda"
    manufacturer_article: str | None = None
    seller_article: str | None = None
    wb_article: str | None = None
    barcode: str | None = None
    brand: str | None = None
    subject: str | None = None
    name: str | None = None
    purchase_price: Decimal | None = None
    retail_price: Decimal | None = None
    pack_units: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class WBStockSnapshotInput(BaseModel):
    wb_article: str
    seller_article: str | None = None
    brand: str | None = None
    subject: str | None = None
    stock_qty: int = 0
    in_way_to_client: int = 0
    in_way_from_client: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class WorkbookImportResult(BaseModel):
    supplier: str
    products_imported: int
    mappings_imported: int
    stocks_imported: int
    persisted: bool
