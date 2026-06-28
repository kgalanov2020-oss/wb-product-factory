from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from backend.config import Settings
from backend.mpstats_collector.models import MPStatsSnapshot


async def collect_mpstats_api_snapshot(settings: Settings, query: str) -> MPStatsSnapshot:
    token = settings.mpstats_api_token
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
        "endRow": 30,
        "filterModel": {},
        "sortModel": [{"colId": "revenue", "sort": "desc"}],
    }
    url = "https://mpstats.io/api/analytics/v1/wb/items"
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        response = await client.post(url, headers=headers, params=params, json=body)
    response.raise_for_status()
    payload = response.json()
    rows = _rows(payload)
    competitors = [_normalize_row(row) for row in rows if isinstance(row, dict)]
    return MPStatsSnapshot(
        query=query,
        collected_at=datetime.now(timezone.utc),
        competitors=competitors,
        prices=[item["price"] for item in competitors if item.get("price") is not None],
        sales=[item["sales"] for item in competitors if item.get("sales") is not None],
        revenue=[item["revenue"] for item in competitors if item.get("revenue") is not None],
        raw_payloads=[{"url": str(response.url), "status": response.status_code, "data": payload}],
    )


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
    price = _first_decimal(row, "price", "avg_price", "final_price", "sale_price", "basic_price")
    sales = _first_int(row, "sales", "sales_count", "orders", "purchase", "quantity")
    revenue = _first_decimal(row, "revenue", "turnover", "sales_amount")
    return {
        "source": "mpstats_api",
        "name": _first(row, "name", "title", "subject_name"),
        "brand": _first(row, "brand", "brand_name"),
        "supplier": _first(row, "seller", "supplier", "supplier_name"),
        "nm_id": _first(row, "id", "nm_id", "nmId"),
        "price": price,
        "sales": sales,
        "revenue": revenue,
        "rating": _first(row, "rating", "review_rating"),
        "feedbacks": _first(row, "feedbacks", "comments", "reviews"),
        "raw": row,
    }


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
