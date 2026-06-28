from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from backend.mpstats_collector.models import MPStatsSnapshot

from .models import ProductAnalysis, SupplierProduct


PRICE_KEYS = ("price", "цена", "стоимость")
SALES_KEYS = ("sales", "sale", "продаж", "выкуп")
REVENUE_KEYS = ("revenue", "выруч", "оборот")
MAX_ESTIMATED_SALES = 2_000_000_000


def build_market_analysis(product: SupplierProduct, snapshot: MPStatsSnapshot) -> ProductAnalysis:
    analysis_data = snapshot.competitors or {
        "prices": snapshot.prices,
        "sales": snapshot.sales,
        "revenue": snapshot.revenue,
    }
    prices = _numbers_by_keys(analysis_data, PRICE_KEYS)
    sales = _numbers_by_keys(analysis_data, SALES_KEYS)
    revenue = _numbers_by_keys(analysis_data, REVENUE_KEYS)
    competitor_count = _competitor_count(snapshot)

    market_min = min(prices) if prices else None
    market_avg = sum(prices) / Decimal(len(prices)) if prices else None
    market_max = max(prices) if prices else None
    estimated_sales = min(int(sum(sales)), MAX_ESTIMATED_SALES) if sales else None
    estimated_revenue = sum(revenue) if revenue else None
    margin = _margin(product.wholesale_price, market_avg)
    score = _launch_score(margin, competitor_count, estimated_sales)
    has_usable_data = any(
        value is not None and value != 0
        for value in (market_avg, competitor_count, estimated_sales, estimated_revenue)
    )

    source_note = (
        "Базовая оценка по публичной выдаче WB. Нужна проверка MPStats для финального решения."
        if _is_wb_public_snapshot(snapshot)
        else "Авторасчет по текущему снимку MPStats. Требует проверки после нормализации данных."
    )
    if competitor_count and market_avg is None:
        source_note = "MPStats API вернул конкурентов, но не вернул цены и продажи на этом тарифе/endpoint."
    if not has_usable_data:
        source_note = "Анализ не дал рыночных данных: MPStats/WB не вернули конкурентов, цены или продажи."

    return ProductAnalysis(
        product_id=product.id,
        status="completed" if has_usable_data else "failed",
        market_price_min=market_min,
        market_price_avg=market_avg,
        market_price_max=market_max,
        competitor_count=competitor_count,
        estimated_sales=estimated_sales,
        estimated_revenue=estimated_revenue,
        margin_percent=margin,
        launch_score=score,
        notes=source_note,
        raw={"mpstats_snapshot": snapshot.model_dump(mode="json")},
    )


def _competitor_count(snapshot: MPStatsSnapshot) -> int:
    if isinstance(snapshot.competitors, list) and snapshot.competitors:
        first = snapshot.competitors[0]
        if isinstance(first, list):
            return len(first)
        return len(snapshot.competitors)
    return 0


def _is_wb_public_snapshot(snapshot: MPStatsSnapshot) -> bool:
    if not snapshot.raw_payloads:
        return False
    return any("search.wb.ru" in str(payload.get("url", "")) for payload in snapshot.raw_payloads)


def _numbers_by_keys(data: Any, keys: tuple[str, ...]) -> list[Decimal]:
    found: list[Decimal] = []
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(marker in key_lower for marker in keys):
                found.extend(_numbers(value))
            else:
                found.extend(_numbers_by_keys(value, keys))
    elif isinstance(data, list):
        for item in data:
            found.extend(_numbers_by_keys(item, keys))
    return [number for number in found if Decimal("1") <= number <= Decimal("1000000000")]


def _numbers(value: Any) -> list[Decimal]:
    if isinstance(value, (int, float, Decimal)):
        return [_to_decimal(value)] if _to_decimal(value) is not None else []
    if isinstance(value, str):
        values: list[Decimal] = []
        for match in re.finditer(r"\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d+)?|\d+", value):
            number = _to_decimal(match.group(0).replace(" ", "").replace("\u00a0", ""))
            if number is not None:
                values.append(number)
        return values
    if isinstance(value, list):
        result: list[Decimal] = []
        for item in value:
            result.extend(_numbers(item))
        return result
    if isinstance(value, dict):
        result: list[Decimal] = []
        for item in value.values():
            result.extend(_numbers(item))
        return result
    return []


def _to_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _margin(cost: Decimal | None, market_avg: Decimal | None) -> float | None:
    if cost is None or market_avg is None or market_avg <= 0:
        return None
    return float(((market_avg - cost) / market_avg) * Decimal("100"))


def _launch_score(
    margin_percent: float | None,
    competitor_count: int | None,
    estimated_sales: int | None,
) -> float | None:
    if margin_percent is None:
        return None
    margin_score = min(max(margin_percent, 0), 70) / 70 * 45
    competition_score = 25 if not competitor_count else max(0, 25 - min(competitor_count, 100) * 0.25)
    sales_score = 0
    if estimated_sales:
        sales_score = min(estimated_sales, 1000) / 1000 * 30
    return round(margin_score + competition_score + sales_score, 2)
