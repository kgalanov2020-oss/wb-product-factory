from __future__ import annotations

import asyncio
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

from backend.config import Settings
from backend.supplier_products.mpstats_api import collect_mpstats_api_snapshot
from backend.supplier_products.repository import SupplierProductRepository
from backend.supplier_products.wb_public import get_wb_public_card_price
from backend.wb_api.client import WBApiClient, WBApiRateLimitError

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
        try:
            prices_by_nm = await wb_client.list_prices_by_nm_ids(nm_ids)
        except WBApiRateLimitError:
            prices_by_nm = {}

        semaphore = asyncio.Semaphore(3)

        async def analyze_one(row: dict[str, Any]) -> CrisisPriceRecommendation:
            async with semaphore:
                try:
                    return await self._analyze_row(row, prices_by_nm, request)
                except Exception as exc:
                    return _failed_recommendation(row, exc)

        items = await asyncio.gather(*(analyze_one(row) for row in listed))

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
        current_price_source = "WB price API" if current_price is not None else None
        if current_price is None:
            public_price, public_payload = await _safe_public_price(nm_id)
            if public_price is not None:
                current_price = public_price
                current_discounted = public_price
                current_price_source = "публичная карточка WB"
                current_price_row = {"source": "wb_public_card", "data": public_payload}

        snapshot = await collect_mpstats_api_snapshot(
            self._settings,
            _query(row),
            product_name=name,
            product_sku=manufacturer_article or vendor_code,
            reference_price=_to_decimal(row.get("purchase_price")),
            detail_rows=5,
        )
        own_price = _own_price(snapshot.competitors, nm_id)
        if current_price is None and own_price is not None:
            current_price = own_price
            current_discounted = own_price
            current_price_source = "MPStats"
        competitors = _competitors(snapshot.competitors, own_nm_id=nm_id)
        prices = sorted(point.price for point in competitors if point.price is not None)
        market_avg = _avg(prices)
        market_min = prices[0] if prices else None
        market_median = _percentile(prices, Decimal("0.50"))
        market_max = prices[-1] if prices else None
        orders_30d = sum((point.orders_30d or 0) for point in competitors) if competitors else None
        revenue_30d = sum((point.revenue_30d or Decimal("0")) for point in competitors) if competitors else None

        recommended_price, decision, basis = _recommend_price(
            current_price=current_price,
            current_discounted=current_discounted,
            market_min=market_min,
            max_raise_percent=request.max_raise_percent,
            competitor_count=len(competitors),
            orders_30d=orders_30d,
            stock_qty=stock_qty,
        )
        reason = await _explain_with_ai(
            self._settings,
            name=name,
            stock_qty=stock_qty,
            current_price=current_price,
            current_price_source=current_price_source,
            market_min=market_min,
            market_avg=market_avg,
            market_median=market_median,
            market_max=market_max,
            orders_30d=orders_30d,
            revenue_30d=revenue_30d,
            recommended_price=recommended_price,
            decision=decision,
            basis=basis,
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
            competitor_price_avg=market_avg,
            competitor_price_median=market_median,
            competitor_price_target=_target_from_min(market_min),
            competitor_price_max=market_max,
            orders_30d=orders_30d,
            revenue_30d=revenue_30d,
            recommended_price=recommended_price,
            raise_percent=raise_percent,
            expected_discounted_price=_discounted(recommended_price, current_discount),
            decision=decision,
            reason=reason,
            recommendation_basis=basis,
            current_price_source=current_price_source,
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


def _failed_recommendation(row: dict[str, Any], exc: Exception) -> CrisisPriceRecommendation:
    nm_id = _safe_int(row.get("wb_article")) or 0
    name = row.get("product_name") or row.get("mapping_name") or row.get("seller_article") or str(nm_id)
    return CrisisPriceRecommendation(
        nm_id=nm_id,
        vendor_code=row.get("seller_article"),
        manufacturer_article=row.get("manufacturer_article"),
        name=name,
        brand=row.get("brand"),
        subject=row.get("subject"),
        stock_qty=_safe_int(row.get("stock_qty")) or 0,
        competitor_count=0,
        decision="skip",
        reason=f"Не меняем: не удалось получить рыночные данные по товару. Ошибка: {str(exc)[:250]}",
        recommendation_basis="Нет подтвержденных цен и продаж конкурентов, решение по цене принимать нельзя.",
        raw={"stock_row": row, "error": str(exc)},
    )


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


def _own_price(rows: list[dict[str, Any]], own_nm_id: int) -> Decimal | None:
    for row in rows:
        if _safe_int(row.get("nm_id")) == own_nm_id:
            return _to_decimal(row.get("price"))
    return None


async def _safe_public_price(nm_id: int) -> tuple[Decimal | None, dict[str, Any]]:
    try:
        return await get_wb_public_card_price(nm_id)
    except Exception as exc:
        return None, {"error": str(exc)}


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
    market_min: Decimal | None,
    max_raise_percent: Decimal,
    competitor_count: int,
    orders_30d: int | None,
    stock_qty: int,
) -> tuple[Decimal | None, str, str]:
    if market_min is None:
        return None, "skip", "Нет цен конкурентов MPStats."
    if competitor_count == 0 or not orders_30d or orders_30d <= 0:
        return None, "skip", "Нет подтвержденного спроса по конкурентам за 30 дней."

    target_price = _target_from_min(market_min)
    if target_price is None:
        return None, "skip", "Нет минимальной цены конкурента."
    if current_price is None or current_price <= 0:
        return (
            _round_price(target_price),
            "recommend_raise",
            f"Цель: поставить цену на 2% ниже минимального конкурента ({_money_text(market_min)} -> {_money_text(target_price)}). Текущая цена WB временно недоступна, перед загрузкой нужна ручная проверка.",
        )
    max_price = current_price * (Decimal("1") + max_raise_percent / Decimal("100"))
    candidate = min(target_price, max_price)
    if current_discounted and candidate <= current_discounted * Decimal("1.03"):
        return current_price, "hold", "Не меняем: цена на 2% ниже минимального конкурента дает рост меньше 3%."
    if candidate <= current_price:
        return current_price, "hold", "Не меняем: текущая цена уже не ниже расчетной рыночной цели."
    cap_note = ""
    if candidate < target_price:
        cap_note = f" Рост ограничен лимитом {max_raise_percent}% от текущей цены, поэтому ниже рыночной цели."
    stock_note = " Остаток небольшой, повышение особенно актуально." if stock_qty <= 5 else ""
    return (
        _round_price(candidate),
        "recommend_raise",
        f"Цель: поставить цену на 2% ниже минимального конкурента ({_money_text(market_min)} -> {_money_text(target_price)}).{cap_note}{stock_note}",
    )


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    index = int(((len(values) - 1) * percentile).to_integral_value(rounding=ROUND_HALF_UP))
    return values[max(0, min(index, len(values) - 1))]


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values) / Decimal(len(values))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _target_from_min(market_min: Decimal | None) -> Decimal | None:
    if market_min is None:
        return None
    return market_min * Decimal("0.98")


def _round_price(value: Decimal) -> Decimal:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if rounded >= 100:
        return (rounded / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10") - Decimal("1")
    return rounded


async def _explain_with_ai(
    settings: Settings,
    *,
    name: str,
    stock_qty: int,
    current_price: Decimal | None,
    current_price_source: str | None,
    market_min: Decimal | None,
    market_avg: Decimal | None,
    market_median: Decimal | None,
    market_max: Decimal | None,
    orders_30d: int | None,
    revenue_30d: Decimal | None,
    recommended_price: Decimal | None,
    decision: str,
    basis: str,
) -> str:
    fallback = _deterministic_reason(
        stock_qty=stock_qty,
        current_price=current_price,
        current_price_source=current_price_source,
        market_min=market_min,
        market_avg=market_avg,
        market_median=market_median,
        market_max=market_max,
        orders_30d=orders_30d,
        revenue_30d=revenue_30d,
        recommended_price=recommended_price,
        decision=decision,
        basis=basis,
    )
    if decision != "recommend_raise":
        return fallback
    prompt = (
        "Дай короткое деловое объяснение рекомендации по цене для продавца Wildberries. "
        "Не выдумывай данные, используй только цифры ниже. Обязательно объясни формулу: "
        "рекомендованная цена = минимальная цена релевантного конкурента минус 2%. "
        "Ответ на русском, 2-3 предложения.\n"
        f"Товар: {name}\n"
        f"Остаток: {stock_qty}\n"
        f"Текущая цена: {_money_text(current_price)}; источник: {current_price_source or 'нет'}\n"
        f"Конкуренты: минимум {_money_text(market_min)}, средняя {_money_text(market_avg)}, медиана {_money_text(market_median)}, максимум {_money_text(market_max)}\n"
        f"Заказы конкурентов за 30 дней: {orders_30d or 0}; выручка: {_money_text(revenue_30d)}\n"
        f"Рекомендованная цена: {_money_text(recommended_price)}\n"
        f"Базовая логика: {basis}"
    )
    ai_text = await _openai_text(settings, prompt) or await _gemini_text(settings, prompt)
    return ai_text or fallback


def _deterministic_reason(
    *,
    stock_qty: int,
    current_price: Decimal | None,
    current_price_source: str | None,
    market_min: Decimal | None,
    market_avg: Decimal | None,
    market_median: Decimal | None,
    market_max: Decimal | None,
    orders_30d: int | None,
    revenue_30d: Decimal | None,
    recommended_price: Decimal | None,
    decision: str,
    basis: str,
) -> str:
    if decision != "recommend_raise":
        return basis
    return (
        f"{basis} По релевантным конкурентам: минимум {_money_text(market_min)}, средняя "
        f"{_money_text(market_avg)}, медиана {_money_text(market_median)}, максимум {_money_text(market_max)}; "
        f"за 30 дней {orders_30d or 0} заказов на {_money_text(revenue_30d)}. "
        f"Рекомендация {_money_text(recommended_price)} применима к остатку {stock_qty} шт.; "
        f"текущая цена {_money_text(current_price)} ({current_price_source or 'источник недоступен'})."
    )


async def _openai_text(settings: Settings, prompt: str) -> str | None:
    if not settings.openai_api_key:
        return None
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 180,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        if response.status_code >= 400:
            return None
        data = response.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content")
        return str(text).strip() if text else None
    except Exception:
        return None


async def _gemini_text(settings: Settings, prompt: str) -> str | None:
    if not settings.gemini_api_key:
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={settings.gemini_api_key.get_secret_value()}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(url, json=payload)
        if response.status_code >= 400:
            return None
        data = response.json()
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
        return str(text).strip() if text else None
    except Exception:
        return None


def _money_text(value: Decimal | None) -> str:
    if value is None:
        return "нет данных"
    return f"{value.quantize(Decimal('1'), rounding=ROUND_HALF_UP)} ₽"


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
