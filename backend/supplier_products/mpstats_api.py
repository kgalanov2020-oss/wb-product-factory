from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from backend.config import Settings
from backend.mpstats_collector.models import MPStatsSnapshot


async def collect_mpstats_api_snapshot(settings: Settings, query: str) -> MPStatsSnapshot:
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
        detail_payloads = await _collect_sku_details(client, headers, rows)
    competitors = [
        _normalize_row({**row, "mpstats_full": detail_payloads.get(str(_first(row, "id", "nm_id", "nmId")))})
        for row in rows
        if isinstance(row, dict)
    ]
    return MPStatsSnapshot(
        query=query,
        collected_at=datetime.now(timezone.utc),
        competitors=competitors,
        prices=[item["price"] for item in competitors if item.get("price") is not None],
        sales=[item["sales"] for item in competitors if item.get("sales") is not None],
        revenue=[item["revenue"] for item in competitors if item.get("revenue") is not None],
        raw_payloads=[
            {"url": str(response.url), "status": response.status_code, "data": payload},
            {"url": "https://mpstats.io/api/analytics/v1/wb/items/{id}/full", "status": 200, "data": detail_payloads},
        ],
    )


async def _collect_sku_details(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    rows: list[Any],
) -> dict[str, Any]:
    d2 = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    d1 = (datetime.now(timezone.utc).date() - timedelta(days=31)).isoformat()
    details: dict[str, Any] = {}
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        sku = _first(row, "id", "nm_id", "nmId")
        if not sku:
            continue
        sku_text = str(sku)
        detail_url = f"https://mpstats.io/api/analytics/v1/wb/items/{sku_text}/full"
        try:
            response = await client.get(detail_url, headers=headers, params={"d1": d1, "d2": d2})
            if response.status_code == 200:
                details[sku_text] = response.json()
            else:
                details[sku_text] = {"status": response.status_code, "error": response.text[:500]}
        except httpx.HTTPError as exc:
            details[sku_text] = {"error": str(exc)}
    return details


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
    full = row.get("mpstats_full") if isinstance(row.get("mpstats_full"), dict) else {}
    period_stats = full.get("period_stats") if isinstance(full.get("period_stats"), dict) else {}
    full_price = full.get("price") if isinstance(full.get("price"), dict) else {}
    price = _first_decimal(full_price, "final_price", "wallet_price", "price") or _first_decimal(
        row, "price", "avg_price", "final_price", "sale_price", "basic_price"
    )
    sales = _first_int(period_stats, "sales", "sales_estimated") or _first_int(
        full, "sales", "orders", "quantity"
    ) or _first_int(row, "sales", "sales_count", "orders", "purchase", "quantity")
    revenue = _first_decimal(period_stats, "revenue", "revenue_estimated") or _first_decimal(
        full, "revenue", "turnover", "sales_amount"
    ) or _first_decimal(row, "revenue", "turnover", "sales_amount")
    seller = _first(row, "seller", "supplier", "supplier_name")
    if isinstance(seller, dict):
        seller = seller.get("name") or seller.get("id")
    subject = full.get("subject") if isinstance(full, dict) else None
    return {
        "source": "mpstats_api",
        "name": _first(full, "name", "full_name") or _first(row, "name", "title", "subject_name"),
        "brand": _first(full, "brand") or _brand_name(_first(row, "brand", "brand_name")),
        "supplier": seller,
        "nm_id": _first(row, "id", "nm_id", "nmId"),
        "price": price,
        "sales": sales,
        "revenue": revenue,
        "rating": _first(full, "rating", "rating_mpstats") or _first(row, "rating", "review_rating"),
        "feedbacks": _first(full, "comments") or _first(row, "feedbacks", "comments", "reviews"),
        "subject": subject.get("name") if isinstance(subject, dict) else None,
        "stock": _first(full, "balance"),
        "url": _first(full, "link") or _first(row, "url"),
        "thumb": _first(row, "thumb"),
        "period_stats": period_stats or None,
        "raw": row,
    }


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
