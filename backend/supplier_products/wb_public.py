from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from backend.mpstats_collector.models import MPStatsSnapshot


async def collect_wb_public_snapshot(query: str) -> MPStatsSnapshot:
    params = {
        "ab_testing": "false",
        "appType": "1",
        "curr": "rub",
        "dest": "-1257786",
        "page": "1",
        "query": query,
        "resultset": "catalog",
        "sort": "popular",
        "spp": "30",
        "suppressSpellcheck": "false",
    }
    url = "https://search.wb.ru/exactmatch/ru/common/v9/search"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    products = payload.get("data", {}).get("products", [])
    competitors = [_normalize_product(product) for product in products if isinstance(product, dict)]
    return MPStatsSnapshot(
        query=query,
        collected_at=datetime.now(timezone.utc),
        competitors=competitors,
        prices=[item["price"] for item in competitors if item.get("price") is not None],
        sales=[item["sales_proxy"] for item in competitors if item.get("sales_proxy") is not None],
        revenue=[item["revenue_proxy"] for item in competitors if item.get("revenue_proxy") is not None],
        raw_payloads=[{"url": str(response.url), "status": response.status_code, "data": payload}],
    )


def _normalize_product(product: dict[str, Any]) -> dict[str, Any]:
    price = _price(product)
    sales_proxy = _number(product.get("feedbacks")) or _number(product.get("reviewRating")) or 0
    return {
        "source": "wb_public_search",
        "name": product.get("name"),
        "brand": product.get("brand"),
        "supplier": product.get("supplier"),
        "nm_id": product.get("id"),
        "price": price,
        "rating": product.get("rating"),
        "feedbacks": product.get("feedbacks"),
        "sales_proxy": sales_proxy,
        "revenue_proxy": float(price * Decimal(sales_proxy)) if price is not None and sales_proxy else None,
    }


def _price(product: dict[str, Any]) -> Decimal | None:
    for key in ("salePriceU", "priceU"):
        value = _number(product.get(key))
        if value:
            return Decimal(value) / Decimal("100")
    sizes = product.get("sizes")
    if isinstance(sizes, list):
        for size in sizes:
            if not isinstance(size, dict):
                continue
            price = size.get("price") if isinstance(size.get("price"), dict) else {}
            value = _number(price.get("total") or price.get("product") or price.get("basic"))
            if value:
                return Decimal(value) / Decimal("100")
    return None


def _number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
