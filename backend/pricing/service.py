from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.config import Settings
from backend.supplier_products.mpstats_api import collect_mpstats_api_snapshot
from backend.supplier_products.repository import SupplierProductRepository
from backend.wb_api.client import WBApiClient

from .models import (
    CompetitorPricePoint,
    CrisisPriceRecommendation,
    CrisisPricingRequest,
    CrisisPricingResult,
    PriceUploadRequest,
    PriceUploadResult,
)


class CrisisPricingService:
    def __init__(
        self,
        repository: SupplierProductRepository,
        settings: Settings,
        wb_client: WBApiClient | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._wb_client = wb_client

    async def analyze(self, request: CrisisPricingRequest) -> CrisisPricingResult:
        wb_client = self._wb_client or WBApiClient(self._settings)
        listed = await self._repository.list_listed_products_with_stock(
            limit=request.limit,
            supplier=request.supplier,
            min_stock=request.min_stock,
            only_with_stock=request.only_with_stock,
        )
        nm_ids = [int(row["wb_article"]) for row in listed if row.get("wb_article")]
        prices_by_nm = await wb_client.list_prices_by_nm_ids(nm_ids)

        items: list[CrisisPriceRecommendation] = []
        for row in listed:
            recommendation = await self._analyze_row(row, prices_by_nm, request)
            items.append(recommendation)

        recommended = sum(1 for item in items if item.decision == "recommend_raise")
        return CrisisPricingResult(
            requested=len(listed),
            analyzed=len(items),
            recommended=recommended,
            skipped=len(items) - recommended,
            items=items,
        )

    async def upload_prices(self, request: PriceUploadRequest) -> PriceUploadResult:
        payload = {
            "data": [
                {
                    "nmID": item.nm_id,
                    "price": item.price,
                    **({"discount": item.discount} if item.discount is not None else {}),
                }
                for item in request.items
            ]
        }
        if request.dry_run:
            return PriceUploadResult(dry_run=True, uploaded=0, payload=payload)
        wb_client = self._wb_client or WBApiClient(self._settings)
        result = await wb_client.upload_prices(payload["data"])
        return PriceUploadResult(dry_run=False, uploaded=len(request.items), payload=result)

    async def _analyze_row(
        self,
        row: dict[str, Any],
        prices_by_nm: dict[int, dict[str, Any]],
        request: CrisisPricingRequest,
    ) -> CrisisPriceRecommendation:
        nm_id = int(row["wb_article"])
        vendor_code = row.get("seller_article")
        manufacturer_article = row.get("manufacturer_article")
        name = row.get("product_name") or row.get("mapping_name") or vendor_code or str(nm_id)
        stock_qty = int(row.get("stock_qty") or 0)
        current_price_row = prices_by_nm.get(nm_id, {})
        current_price, current_discount, current_discounted = _current_prices(current_price_row)

        snapshot = await collect_mpstats_api_snapshot(
            self._settings,
            _query(row),
            product_name=name,
            product_sku=manufacturer_article or vendor_code,
            reference_price=_to_decimal(row.get("purchase_price")),
        )
        competitors = _competitors(snapshot.competitors, own_nm_id=nm_id)
        prices = sorted(point.price for point in competitors if point.price is not None)
        target_price = _percentile(prices, request.target_percentile)
        market_min = prices[0] if prices else None
        market_median = _percentile(prices, Decimal("0.50"))
        market_max = prices[-1] if prices else None
        orders_30d = sum((point.orders_30d or 0) for point in competitors) if competitors else None
        revenue_30d = sum((point.revenue_30d or Decimal("0")) for point in competitors) if competitors else None

        recommended_price, decision, reason = _recommend_price(
            current_price=current_price,
            current_discounted=current_discounted,
            target_price=target_price,
            max_raise_percent=request.max_raise_percent,
            competitor_count=len(competitors),
            orders_30d=orders_30d,
            stock_qty=stock_qty,
        )
        raise_percent = None
        if recommended_price is not None and current_price and current_price > 0:
            raise_percent = ((recommended_price - current_price) / current_price * Decimal("100")).quantize(
                Decimal("0.1"),
                rounding=ROUND_HALF_UP,
            )

        return CrisisPriceRecommendation(
            nm_id=nm_id,
            vendor_code=vendor_code,
            manufacturer_article=manufacturer_article,
            name=name,
            brand=row.get("brand"),
            subject=row.get("subject"),
            stock_qty=stock_qty,
            current_price=current_price,
            current_discount=current_discount,
            current_discounted_price=current_discounted,
            competitor_count=len(competitors),
            competitor_price_min=market_min,
            competitor_price_median=market_median,
            competitor_price_target=target_price,
            competitor_price_max=market_max,
            orders_30d=orders_30d,
            revenue_30d=revenue_30d,
            recommended_price=recommended_price,
            raise_percent=raise_percent,
            expected_discounted_price=_discounted(recommended_price, current_discount),
            decision=decision,
            reason=reason,
            competitors=competitors[:10],
            raw={"price_row": current_price_row, "stock_row": row, "mpstats": snapshot.model_dump(mode="json")},
        )


def _query(row: dict[str, Any]) -> str:
    parts = [
        "Звезда",
        row.get("manufacturer_article"),
        row.get("product_name") or row.get("mapping_name"),
    ]
    return " ".join(str(part).strip() for part in parts if part).strip()[:300]


def _competitors(rows: list[dict[str, Any]], own_nm_id: int) -> list[CompetitorPricePoint]:
    competitors: list[CompetitorPricePoint] = []
    for row in rows:
        nm_id = _safe_int(row.get("nm_id"))
        if nm_id == own_nm_id:
            continue
        periods = row.get("periods") if isinstance(row.get("periods"), dict) else {}
        month = periods.get("month") if isinstance(periods.get("month"), dict) else {}
        competitors.append(
            CompetitorPricePoint(
                nm_id=nm_id,
                name=row.get("name"),
                brand=_entity(row.get("brand")),
                seller=_entity(row.get("supplier")),
                price=_to_decimal(row.get("price")),
                orders_30d=_safe_int(month.get("sales") or row.get("sales")),
                revenue_30d=_to_decimal(month.get("revenue") or row.get("revenue")),
                stock=_safe_int(row.get("stock")),
                url=row.get("url"),
            )
        )
    return [item for item in competitors if item.price is not None]


def _current_prices(row: dict[str, Any]) -> tuple[Decimal | None, int | None, Decimal | None]:
    price = None
    discount = _safe_int(row.get("discount"))
    discounted = None
    sizes = row.get("sizes") if isinstance(row.get("sizes"), list) else []
    if sizes:
        first = sizes[0] if isinstance(sizes[0], dict) else {}
        price = _to_decimal(first.get("price"))
        discounted = _to_decimal(first.get("discountedPrice"))
    price = price or _to_decimal(row.get("price"))
    discounted = discounted or _discounted(price, discount)
    return price, discount, discounted


def _recommend_price(
    current_price: Decimal | None,
    current_discounted: Decimal | None,
    target_price: Decimal | None,
    max_raise_percent: Decimal,
    competitor_count: int,
    orders_30d: int | None,
    stock_qty: int,
) -> tuple[Decimal | None, str, str]:
    if current_price is None or current_price <= 0:
        return None, "skip", "Нет текущей цены WB, менять нельзя."
    if target_price is None:
        return None, "skip", "Нет цен конкурентов MPStats."
    if competitor_count == 0 or not orders_30d or orders_30d <= 0:
        return None, "skip", "Нет подтвержденного спроса по конкурентам за 30 дней."

    max_price = current_price * (Decimal("1") + max_raise_percent / Decimal("100"))
    candidate = min(target_price, max_price)
    if stock_qty <= 5:
        candidate = min(candidate * Decimal("1.08"), max_price)
    if current_discounted and candidate <= current_discounted * Decimal("1.03"):
        return current_price, "hold", "Рынок не дает смысленного повышения: рост меньше 3%."
    if candidate <= current_price:
        return current_price, "hold", "Текущая цена уже на уровне рынка или выше."
    return _round_price(candidate), "recommend_raise", "Есть остаток и рынок поднял цену: можно повысить после согласования."


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    index = int(((len(values) - 1) * percentile).to_integral_value(rounding=ROUND_HALF_UP))
    return values[max(0, min(index, len(values) - 1))]


def _round_price(value: Decimal) -> Decimal:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if rounded >= 100:
        return (rounded / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10") - Decimal("1")
    return rounded


def _discounted(price: Decimal | None, discount: int | None) -> Decimal | None:
    if price is None:
        return None
    if not discount:
        return price
    return (price * (Decimal("100") - Decimal(discount)) / Decimal("100")).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )


def _entity(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name") or str(value.get("id") or "")
    return str(value) if value else None


def _to_decimal(value: Any) -> Decimal | None:
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(Decimal(str(value).replace(" ", "").replace(",", ".")))
    except Exception:
        return None
