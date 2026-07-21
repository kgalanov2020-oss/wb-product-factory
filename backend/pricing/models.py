from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class CrisisPricingRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    supplier: str = "zvezda"
    max_raise_percent: Decimal = Field(default=Decimal("35"), ge=0, le=300)
    target_percentile: Decimal = Field(default=Decimal("0.75"), ge=Decimal("0.1"), le=Decimal("0.95"))
    min_stock: int = Field(default=1, ge=0)
    only_with_stock: bool = True


class CompetitorPricePoint(BaseModel):
    nm_id: int | None = None
    name: str | None = None
    brand: str | None = None
    seller: str | None = None
    price: Decimal | None = None
    orders_30d: int | None = None
    revenue_30d: Decimal | None = None
    stock: int | None = None
    url: str | None = None


class CrisisPriceRecommendation(BaseModel):
    nm_id: int
    vendor_code: str | None = None
    manufacturer_article: str | None = None
    name: str
    brand: str | None = None
    subject: str | None = None
    stock_qty: int
    current_price: Decimal | None = None
    current_discount: int | None = None
    current_seller_discounted_price: Decimal | None = None
    current_discounted_price: Decimal | None = None
    competitor_count: int
    competitor_price_min: Decimal | None = None
    competitor_price_avg: Decimal | None = None
    competitor_price_median: Decimal | None = None
    competitor_price_target: Decimal | None = None
    competitor_price_max: Decimal | None = None
    orders_30d: int | None = None
    revenue_30d: Decimal | None = None
    recommended_price: Decimal | None = None
    recommended_discount: int | None = None
    raise_percent: Decimal | None = None
    expected_discounted_price: Decimal | None = None
    decision: Literal["recommend_raise", "hold", "skip"] = "skip"
    reason: str
    recommendation_basis: str | None = None
    current_price_source: str | None = None
    competitors: list[CompetitorPricePoint] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CrisisPricingResult(BaseModel):
    requested: int
    analyzed: int
    recommended: int
    skipped: int
    items: list[CrisisPriceRecommendation]


class PriceApprovalItem(BaseModel):
    nm_id: int
    price: int = Field(gt=0)
    discount: int | None = Field(default=None, ge=0, le=99)
    expected_site_price: Decimal | None = Field(default=None, gt=0)


class PriceUploadRequest(BaseModel):
    items: list[PriceApprovalItem] = Field(min_length=1, max_length=1000)
    dry_run: bool = True


class PriceUploadResult(BaseModel):
    dry_run: bool
    uploaded: int
    payload: dict[str, Any]


class PriceMonitorItem(BaseModel):
    nm_id: int
    expected_site_price: Decimal | None = None
    current_base_price: Decimal | None = None
    current_seller_discount: int | None = None
    current_seller_price: Decimal | None = None
    current_site_price: Decimal | None = None
    delta: Decimal | None = None
    status: Literal["ok", "wait", "no_data"] = "no_data"
    source: str | None = None


class PriceMonitorRequest(BaseModel):
    nm_ids: list[int] = Field(min_length=1, max_length=100)
    expected_site_prices: dict[int, Decimal] = Field(default_factory=dict)
    tolerance_percent: Decimal = Field(default=Decimal("3"), ge=0, le=50)


class PriceMonitorResult(BaseModel):
    checked: int
    ok: int
    wait: int
    items: list[PriceMonitorItem]
