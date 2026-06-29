from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from backend.mpstats_collector.models import MPStatsSnapshot

from .models import ProductAnalysis, SupplierProduct


PRICE_KEYS = ("price", "цена", "стоимость")
SALES_KEYS = ("sales", "sale", "продаж", "выкуп")
REVENUE_KEYS = ("revenue", "выруч", "оборот")
MAX_ESTIMATED_SALES = 2_000_000_000
ANALYSIS_VERSION = "zvezda_relevance_v2"


def build_market_analysis(product: SupplierProduct, snapshot: MPStatsSnapshot) -> ProductAnalysis:
    competitors = [item for item in snapshot.competitors if isinstance(item, dict)]
    prices = [_to_decimal(item.get("price")) for item in competitors]
    prices = [price for price in prices if price is not None and Decimal("1") <= price <= Decimal("1000000000")]
    period_rollups = _period_rollups(competitors)
    month_rollup = period_rollups.get("month", {})
    competitor_count = _competitor_count(snapshot)

    market_min = min(prices) if prices else None
    market_avg = sum(prices) / Decimal(len(prices)) if prices else None
    market_max = max(prices) if prices else None
    estimated_sales = month_rollup.get("sales")
    estimated_revenue = month_rollup.get("revenue")
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
    has_period_sales = _has_period_sales(period_rollups)
    missing_period_sales = not has_period_sales
    if missing_period_sales:
        has_usable_data = False
        source_note = "Нет подтвержденных продаж и выручки по периодам MPStats. Решение о запуске принимать нельзя."
    if not has_usable_data and not missing_period_sales:
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
        raw={
            "analysis_version": ANALYSIS_VERSION,
            "analysis_period": {
                "label": "последние 30 дней",
                "date_from": (datetime.now(timezone.utc).date() - timedelta(days=31)).isoformat(),
                "date_to": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
                "sales_basis": "сумма заказов найденных конкурентов за период",
                "revenue_basis": "сумма заказов в рублях найденных конкурентов за период",
                "price_basis": "минимальная / средняя / максимальная цена найденных конкурентов",
                "margin_basis": "грубая маржа = (средняя цена рынка - закупка) / средняя цена рынка; без комиссий WB, логистики, налогов и рекламы",
                "score_basis": "score = маржа до 45 баллов + низкая конкуренция до 25 баллов + продажи до 30 баллов",
            },
            "period_rollups": period_rollups,
            "mpstats_snapshot": snapshot.model_dump(mode="json"),
        },
    )


def _competitor_count(snapshot: MPStatsSnapshot) -> int:
    if isinstance(snapshot.competitors, list) and snapshot.competitors:
        first = snapshot.competitors[0]
        if isinstance(first, list):
            return len(first)
        return len(snapshot.competitors)
    return 0


def _has_period_sales(period_rollups: dict[str, dict[str, Any]]) -> bool:
    month = period_rollups.get("month") or {}
    sales = _to_decimal(month.get("sales"))
    revenue = _to_decimal(month.get("revenue"))
    return bool(sales and sales > 0 and revenue and revenue > 0)


def _is_wb_public_snapshot(snapshot: MPStatsSnapshot) -> bool:
    if not snapshot.raw_payloads:
        return False
    return any("search.wb.ru" in str(payload.get("url", "")) for payload in snapshot.raw_payloads)


def _period_rollups(competitors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    labels = {
        "week": "7 дней",
        "month": "30 дней",
        "quarter": "90 дней",
        "year_to_date": "с начала года",
    }
    rollups: dict[str, dict[str, Any]] = {}
    for period_key, label in labels.items():
        sales_total = 0
        revenue_total = Decimal("0")
        buyouts_total = 0
        buyout_revenue_total = Decimal("0")
        sales_found = False
        revenue_found = False
        buyouts_found = False
        buyout_revenue_found = False
        date_from = None
        date_to = None
        for competitor in competitors:
            periods = competitor.get("periods") if isinstance(competitor.get("periods"), dict) else {}
            period = periods.get(period_key) if isinstance(periods.get(period_key), dict) else {}
            sales = _to_decimal(period.get("sales"))
            revenue = _to_decimal(period.get("revenue"))
            buyouts = _to_decimal(period.get("buyouts"))
            buyout_revenue = _to_decimal(period.get("buyout_revenue"))
            if sales is not None:
                sales_total += int(sales)
                sales_found = True
            if revenue is not None:
                revenue_total += revenue
                revenue_found = True
            if buyouts is not None:
                buyouts_total += int(buyouts)
                buyouts_found = True
            if buyout_revenue is not None:
                buyout_revenue_total += buyout_revenue
                buyout_revenue_found = True
            date_from = date_from or period.get("date_from")
            date_to = date_to or period.get("date_to")
        rollups[period_key] = {
            "label": label,
            "date_from": date_from,
            "date_to": date_to,
            "sales": min(sales_total, MAX_ESTIMATED_SALES) if sales_found else None,
            "revenue": revenue_total if revenue_found else None,
            "buyouts": min(buyouts_total, MAX_ESTIMATED_SALES) if buyouts_found else None,
            "buyout_revenue": buyout_revenue_total if buyout_revenue_found else None,
        }
    return rollups


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
