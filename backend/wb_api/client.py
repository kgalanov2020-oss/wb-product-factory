from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from backend.config import Settings


class WBApiConfigurationError(RuntimeError):
    pass


class WBApiClient:
    def __init__(self, settings: Settings) -> None:
        token = settings.wb_api_secret
        if token is None:
            raise WBApiConfigurationError("WB_API_TOKEN is not configured")
        self._token = token.get_secret_value()
        self._prices_base_url = str(settings.wb_prices_base_url).rstrip("/")
        self._statistics_base_url = str(settings.wb_statistics_base_url).rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._token, "Accept": "application/json"}

    async def list_prices(self, limit: int = 1000) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        offset = 0
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            while True:
                response = await client.get(
                    f"{self._prices_base_url}/api/v2/list/goods/filter",
                    headers=self._headers,
                    params={"limit": limit, "offset": offset},
                )
                response.raise_for_status()
                payload = response.json()
                items = ((payload.get("data") or {}).get("listGoods") or []) if isinstance(payload, dict) else []
                if not items:
                    break
                for item in items:
                    nm_id = _safe_int(item.get("nmID"))
                    if nm_id is not None:
                        result[nm_id] = item
                if len(items) < limit:
                    break
                offset += limit
        return result

    async def list_stocks(self, date_from: date | None = None) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(
                f"{self._statistics_base_url}/api/v1/supplier/stocks",
                headers=self._headers,
                params={"dateFrom": (date_from or date(2019, 1, 1)).isoformat()},
            )
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, list) else []

    async def upload_prices(self, items: list[dict[str, int]]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            response = await client.post(
                f"{self._prices_base_url}/api/v2/upload/task",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"data": items},
            )
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {"raw": payload}


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(str(value))
    except (TypeError, ValueError):
        return None
