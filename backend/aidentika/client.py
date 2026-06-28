from __future__ import annotations

from typing import Any

import httpx

from backend.config import Settings

from .exceptions import AidentikaAPIError, AidentikaConfigurationError
from .models import (
    AidentikaActionResponse,
    AidentikaAnalyzeRequest,
    AidentikaCardGenerationRequest,
    AidentikaPhotoGenerationRequest,
    AidentikaStatusResponse,
)


class AidentikaClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.aidentika_configured:
            raise AidentikaConfigurationError("AIDENTIKA_API_KEY is not configured")
        assert settings.aidentika_api_key is not None
        self._base_url = str(settings.aidentika_base_url).rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.aidentika_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        self._timeout = httpx.Timeout(60.0)

    async def analyze(self, request: AidentikaAnalyzeRequest) -> dict[str, Any]:
        return await self._post("/analyze", request.model_dump(mode="json", exclude_none=True))

    async def generate_photo(
        self,
        request: AidentikaPhotoGenerationRequest,
        idempotency_key: str | None = None,
    ) -> AidentikaActionResponse:
        data = await self._post(
            "/generate/photo",
            request.model_dump(mode="json", exclude_none=True),
            idempotency_key=idempotency_key,
        )
        return AidentikaActionResponse.model_validate(data)

    async def generate_card(
        self,
        request: AidentikaCardGenerationRequest,
        idempotency_key: str | None = None,
    ) -> AidentikaActionResponse:
        data = await self._post(
            "/generate/card",
            request.model_dump(mode="json", exclude_none=True),
            idempotency_key=idempotency_key,
        )
        return AidentikaActionResponse.model_validate(data)

    async def get_status(self, action_id: int) -> AidentikaStatusResponse:
        data = await self._get(f"/status/{action_id}")
        return AidentikaStatusResponse.model_validate({**data, "action_id": action_id, "raw": data})

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = dict(self._headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}{path}", headers=headers, json=payload)
        return self._parse_response(response)

    async def _get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(f"{self._base_url}{path}", headers=self._headers)
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise AidentikaAPIError(
                f"Aidentika returned non-JSON response: {response.status_code}"
            ) from exc
        if response.is_error:
            detail = data.get("detail") or data.get("error") or data.get("message") or data
            raise AidentikaAPIError(f"Aidentika request failed: {response.status_code} {detail}")
        if not isinstance(data, dict):
            raise AidentikaAPIError("Aidentika returned unexpected response payload")
        return data
