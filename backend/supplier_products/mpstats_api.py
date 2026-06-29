from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from backend.config import Settings
from backend.mpstats_collector.models import MPStatsSnapshot


async def collect_mpstats_api_snapshot(
    settings: Settings,
    query: str,
    product_name: str | None = None,
    product_sku: str | None = None,
    reference_price: Decimal | None = None,
) -> MPStatsSnapshot:
    token = settings.mpstats_api_secret
    if token is None:
        raise RuntimeError("MPStats API token is not configured")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Mpstats-TOKEN": token.get_secret_value(),
    }
    params = {"keyword": query}
    body = {
        "startRow": 0,
        "endRow": 50,
        "filterModel": {},
        "sortModel": [{"colId": "revenue", "sort": "desc"}],
    }
    url = "https://mpstats.io/api/analytics/v1/wb/items"
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        response = await client.post(url, headers=headers, params=params, json=body)
        response.raise_for_status()
        payload = response.json()
        rows = _rows(payload)
        detail_payloads = await _collect_sku_details(client, headers, rows)
    all_competitors = [
        _normalize_row(
            {**row, "mpstats_details": detail_payloads.get(str(_first(row, "id", "nm_id", "nmId")), {})}
        )
        for row in rows
        if isinstance(row, dict)
    ]
    competitors = _filter_relevant_competitors(
        all_competitors,
        product_name=product_name or query,
        product_sku=product_sku,
        reference_price=reference_price,
    )
    return MPStatsSnapshot(
        query=query,
        collected_at=datetime.now(timezone.utc),
        competitors=competitors,
        prices=[item["price"] for item in competitors if item.get("price") is not None],
        sales=[
            item.get("periods", {}).get("month", {}).get("sales")
            for item in competitors
            if item.get("periods", {}).get("month", {}).get("sales") is not None
        ],
        revenue=[
            item.get("periods", {}).get("month", {}).get("revenue")
            for item in competitors
            if item.get("periods", {}).get("month", {}).get("revenue") is not None
        ],
        raw_payloads=[
            {"url": str(response.url), "status": response.status_code, "data": payload},
            {"url": "https://mpstats.io/api/analytics/v1/wb/items/{id}/full", "status": 200, "data": detail_payloads},
            {
                "url": "internal://relevance-filter",
                "status": 200,
                "data": {
                    "found": len(all_competitors),
                    "kept": len(competitors),
                    "query": query,
                    "product_name": product_name,
                    "product_sku": product_sku,
                },
            },
        ],
    )


async def _collect_sku_details(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    rows: list[Any],
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    semaphore = asyncio.Semaphore(6)
    periods = _periods()

    async def fetch_period(sku_text: str, period_key: str, d1: str, d2: str) -> tuple[str, str, Any]:
        detail_url = f"https://mpstats.io/api/analytics/v1/wb/items/{sku_text}/full"
        async with semaphore:
            try:
                response = await client.get(detail_url, headers=headers, params={"d1": d1, "d2": d2})
                if response.status_code == 200:
                    return sku_text, period_key, response.json()
                return sku_text, period_key, {"status": response.status_code, "error": response.text[:500]}
            except httpx.HTTPError as exc:
                return sku_text, period_key, {"error": str(exc)}

    tasks = []
    for row in rows[:15]:
        if not isinstance(row, dict):
            continue
        sku = _first(row, "id", "nm_id", "nmId")
        if not sku:
            continue
        sku_text = str(sku)
        for period_key, (d1, d2) in periods.items():
            tasks.append(fetch_period(sku_text, period_key, d1, d2))
    for sku_text, period_key, payload in await asyncio.gather(*tasks):
        details.setdefault(sku_text, {})[period_key] = payload
    return details


def _periods() -> dict[str, tuple[str, str]]:
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    return {
        "week": ((end - timedelta(days=7)).isoformat(), end.isoformat()),
        "month": ((end - timedelta(days=31)).isoformat(), end.isoformat()),
        "quarter": ((end - timedelta(days=92)).isoformat(), end.isoformat()),
        "year_to_date": (date(end.year, 1, 1).isoformat(), end.isoformat()),
    }


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "rows", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _rows(value)
            if nested:
                return nested
    return []


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("mpstats_details") if isinstance(row.get("mpstats_details"), dict) else {}
    month_full = details.get("month") if isinstance(details.get("month"), dict) else {}
    if not month_full and isinstance(row.get("mpstats_full"), dict):
        month_full = row["mpstats_full"]
    period_stats = month_full.get("period_stats") if isinstance(month_full.get("period_stats"), dict) else {}
    full_price = month_full.get("price") if isinstance(month_full.get("price"), dict) else {}
    price = _first_decimal(full_price, "final_price", "wallet_price", "price") or _first_decimal(
        row, "price", "avg_price", "final_price", "sale_price", "basic_price"
    )
    sales = _order_count(period_stats) or _order_count(month_full) or _order_count(row)
    revenue = _order_revenue(period_stats) or _order_revenue(month_full) or _order_revenue(row)
    buyouts = _buyout_count(period_stats) or _buyout_count(month_full) or _buyout_count(row)
    buyout_revenue = _buyout_revenue(period_stats) or _buyout_revenue(month_full) or _buyout_revenue(row)
    seller = _first(row, "seller", "supplier", "supplier_name")
    if isinstance(seller, dict):
        seller = seller.get("name") or seller.get("id")
    subject = month_full.get("subject") if isinstance(month_full, dict) else None
    return {
        "source": "mpstats_api",
        "name": _first(month_full, "name", "full_name") or _first(row, "name", "title", "subject_name"),
        "brand": _first(month_full, "brand") or _brand_name(_first(row, "brand", "brand_name")),
        "supplier": seller,
        "nm_id": _first(row, "id", "nm_id", "nmId"),
        "price": price,
        "sales": sales,
        "revenue": revenue,
        "buyouts": buyouts,
        "buyout_revenue": buyout_revenue,
        "rating": _first(month_full, "rating", "rating_mpstats") or _first(row, "rating", "review_rating"),
        "feedbacks": _first(month_full, "comments") or _first(row, "feedbacks", "comments", "reviews"),
        "subject": subject.get("name") if isinstance(subject, dict) else None,
        "stock": _first(month_full, "balance"),
        "url": _first(month_full, "link") or _first(row, "url"),
        "thumb": _first(row, "thumb"),
        "period_stats": period_stats or None,
        "periods": _normalize_periods(details),
        "relevance_score": 0,
        "raw": row,
    }


def _normalize_periods(details: dict[str, Any]) -> dict[str, dict[str, Any]]:
    periods = _periods()
    result: dict[str, dict[str, Any]] = {}
    for period_key, payload in details.items():
        if not isinstance(payload, dict):
            continue
        stats = payload.get("period_stats") if isinstance(payload.get("period_stats"), dict) else {}
        result[period_key] = {
            "date_from": periods.get(period_key, ("", ""))[0],
            "date_to": periods.get(period_key, ("", ""))[1],
            "sales": _order_count(stats) or _order_count(payload),
            "revenue": _order_revenue(stats) or _order_revenue(payload),
            "buyouts": _buyout_count(stats) or _buyout_count(payload),
            "buyout_revenue": _buyout_revenue(stats) or _buyout_revenue(payload),
        }
    return result


def _filter_relevant_competitors(
    competitors: list[dict[str, Any]],
    product_name: str,
    product_sku: str | None,
    reference_price: Decimal | None,
) -> list[dict[str, Any]]:
    product_tokens = _tokens(product_name)
    sku_tokens = _tokens(product_sku or "")
    is_generic_query = len(product_tokens) <= 2
    kept: list[dict[str, Any]] = []
    for competitor in competitors:
        text = " ".join(
            str(value or "")
            for value in (
                competitor.get("name"),
                competitor.get("brand"),
                competitor.get("supplier"),
                competitor.get("subject"),
            )
        )
        tokens = _tokens(text)
        shared = product_tokens & tokens
        has_zvezda = "звезда" in tokens or "zvezda" in tokens
        has_sku = bool(sku_tokens and sku_tokens & tokens)
        score = len(shared)
        if has_zvezda:
            score += 3
        if has_sku:
            score += 5
        if product_tokens and product_tokens <= tokens:
            score += 4
        price = competitor.get("price")
        if isinstance(price, Decimal) and reference_price and reference_price > 0:
            ratio = price / reference_price
            if ratio > Decimal("8") or ratio < Decimal("0.35"):
                score -= 4
        if is_generic_query and not (has_zvezda or has_sku):
            continue
        if score >= 2:
            competitor["relevance_score"] = score
            kept.append(competitor)
    kept.sort(key=lambda item: (item.get("relevance_score") or 0, item.get("revenue") or 0), reverse=True)
    return kept[:15]


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]+", value.lower())
    stop_words = {
        "для",
        "без",
        "или",
        "при",
        "что",
        "это",
        "шт",
        "мл",
        "кг",
        "гр",
        "см",
        "мм",
        "товар",
    }
    return {word for word in words if len(word) > 1 and word not in stop_words}


def _brand_name(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("id")
    return value


def _first(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _first_decimal(row: dict[str, Any], *keys: str) -> Decimal | None:
    value = _first(row, *keys)
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except Exception:
        return None


def _first_int(row: dict[str, Any], *keys: str) -> int | None:
    decimal = _first_decimal(row, *keys)
    return int(decimal) if decimal is not None else None


def _order_count(row: dict[str, Any]) -> int | None:
    return _first_int(
        row,
        "orders",
        "orders_count",
        "orders_qty",
        "orders_quantity",
        "ordered",
        "quantity",
        "sales",
        "sales_count",
        "sales_estimated",
        "purchase",
    )


def _order_revenue(row: dict[str, Any]) -> Decimal | None:
    return _first_decimal(
        row,
        "orders_sum",
        "orders_amount",
        "orders_revenue",
        "ordered_sum",
        "ordered_amount",
        "orders_rub",
        "revenue",
        "revenue_estimated",
        "turnover",
        "sales_amount",
    )


def _buyout_count(row: dict[str, Any]) -> int | None:
    return _first_int(
        row,
        "buyouts",
        "buyouts_count",
        "buyouts_qty",
        "buyout",
        "purchases",
        "purchase_count",
        "sales",
        "sales_count",
        "sales_estimated",
    )


def _buyout_revenue(row: dict[str, Any]) -> Decimal | None:
    return _first_decimal(
        row,
        "buyouts_sum",
        "buyouts_amount",
        "buyouts_revenue",
        "buyout_sum",
        "buyout_amount",
        "purchase_amount",
        "revenue",
        "revenue_estimated",
        "turnover",
    )
