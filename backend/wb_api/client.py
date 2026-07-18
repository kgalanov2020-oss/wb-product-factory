from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from backend.config import Settings


class WBApiConfigurationError(RuntimeError):
    pass


class WBApiRateLimitError(RuntimeError):
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
                response = await _request_with_retry(
                    client,
                    "GET",
                    f"{self._prices_base_url}/api/v2/list/goods/filter",
                    headers=self._headers,
                    params={"limit": limit, "offset": offset},
                )
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

    async def list_prices_by_nm_ids(self, nm_ids: list[int]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        unique_ids = list(dict.fromkeys(nm_id for nm_id in nm_ids if nm_id > 0))
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            for chunk in _chunks(unique_ids, 1000):
                response = await _request_with_retry(
                    client,
                    "POST",
                    f"{self._prices_base_url}/api/v2/list/goods/filter",
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={"nmList": chunk},
                )
                payload = response.json()
                items = ((payload.get("data") or {}).get("listGoods") or []) if isinstance(payload, dict) else []
                for item in items:
                    nm_id = _safe_int(item.get("nmID"))
                    if nm_id is not None:
                        result[nm_id] = item
                await asyncio.sleep(0.65)
        return result

    async def list_stocks(self, date_from: date | None = None) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await _request_with_retry(
                client,
                "GET",
                f"{self._statistics_base_url}/api/v1/supplier/stocks",
                headers=self._headers,
                params={"dateFrom": (date_from or date(2019, 1, 1)).isoformat()},
            )
            payload = response.json()
        return payload if isinstance(payload, list) else []

    async def upload_prices(self, items: list[dict[str, int]]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            response = await _request_with_retry(
                client,
                "POST",
                f"{self._prices_base_url}/api/v2/upload/task",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"data": items},
            )
            payload = response.json()
        return payload if isinstance(payload, dict) else {"raw": payload}


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 4,
    **kwargs: Any,
) -> httpx.Response:
    for attempt in range(retries + 1):
        response = await client.request(method, url, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response

        retry_after = response.headers.get("Retry-After")
        if attempt >= retries:
            raise WBApiRateLimitError("WB API временно ограничил запросы. Повтори расчет через 1-2 минуты.") from None

        delay = _retry_delay(retry_after, attempt)
        await asyncio.sleep(delay)

    raise WBApiRateLimitError("WB API временно ограничил запросы. Повтори расчет через 1-2 минуты.")


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 60.0)
        except ValueError:
            pass
    return min(2.0 * (attempt + 1), 12.0)


def _chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(str(value))
    except (TypeError, ValueError):
        return None
