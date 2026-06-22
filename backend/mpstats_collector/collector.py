from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Response, async_playwright

from backend.config import Settings

from .exceptions import MPStatsCollectorError, MPStatsConfigurationError
from .models import CollectionRequest, MPStatsSnapshot


class PlaywrightMPStatsCollector:
    """Runs an authenticated MPStats search and captures its JSON datasets."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._allowed_host = (urlparse(str(settings.mpstats_base_url)).hostname or "").lower()
    async def collect(self, request: CollectionRequest) -> MPStatsSnapshot:
        api_payloads: list[dict[str, Any]] = []
        grid_rows: list[dict[str, str]] = []
        storage_path = self._settings.mpstats_storage_state_path
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        json_received = asyncio.Event()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self._settings.mpstats_headless)
            context = await browser.new_context(
                storage_state=str(storage_path) if storage_path.exists() else None
            )
            page = await context.new_page()
            page.set_default_timeout(self._settings.mpstats_timeout_ms)

            async def capture_json(response: Response) -> None:
                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type or not self._is_allowed_url(response.url):
                    return
                try:
                    payload: Any = await response.json()
                except Exception:
                    return
                api_payloads.append({"url": response.url, "status": response.status, "data": payload})
                json_received.set()

            try:
                if not storage_path.exists():
                    await self._login(page, storage_path)
                    await context.storage_state(path=str(storage_path))

                await page.goto(
                    str(self._settings.mpstats_search_url),
                    wait_until="domcontentloaded",
                )
                search_button = page.get_by_role(
                    "button",
                    name="Искать",
                    exact=True,
                )
                query_label = page.get_by_text("Запрос", exact=True)
                if await query_label.count() != 1:
                    raise MPStatsCollectorError("MPStats query field label is not unique")
                search_input = query_label.locator("xpath=following::input[1]")
                await search_input.fill(request.query)
                page.on("response", capture_json)
                await search_button.click()
                try:
                    await asyncio.wait_for(
                        json_received.wait(),
                        timeout=self._settings.mpstats_timeout_ms / 1000,
                    )
                except TimeoutError as exc:
                    raise MPStatsCollectorError(
                        "MPStats search returned no JSON data"
                    ) from exc
                # MPStats loads the result grid through follow-up API requests.
                await page.wait_for_timeout(10_000)
                grid_rows = await self._extract_visible_grid(page)
            finally:
                await context.close()
                await browser.close()

        return MPStatsSnapshot(
            query=request.query,
            collected_at=datetime.now(timezone.utc),
            niches=self._extract(api_payloads, "nich"),
            competitors=grid_rows or self._extract(api_payloads, "compet"),
            sales=self._extract(api_payloads, "sale"),
            prices=self._extract(api_payloads, "price"),
            revenue=self._extract(api_payloads, "revenue"),
            raw_payloads=api_payloads,
        )

    async def _login(self, page: Any, storage_path: Path) -> None:
        if not self._settings.mpstats_login_configured:
            raise MPStatsConfigurationError(
                f"MPStats login settings are required because {storage_path} does not exist"
            )
        password = self._settings.mpstats_password
        assert password is not None
        await page.goto(str(self._settings.mpstats_login_url), wait_until="domcontentloaded")
        email_input = page.locator(
            'input[type="email"]:visible, '
            'input[name="email"]:visible, '
            'input[autocomplete="username"]:visible'
        ).first
        if await email_input.count() == 0:
            email_input = page.locator("input:visible").nth(0)

        await email_input.fill(self._settings.mpstats_email)
        await page.locator('input[type="password"]:visible').first.fill(
            password.get_secret_value()
        )
        await page.get_by_role("button", name="Войти", exact=True).click()
        await page.wait_for_url(lambda url: "/login" not in url)

    @staticmethod
    def _extract(payloads: list[dict[str, Any]], marker: str) -> list[Any]:
        return [item["data"] for item in payloads if marker in item["url"].lower()]

    @staticmethod
    async def _extract_visible_grid(page: Any) -> list[dict[str, str]]:
        for row_selector in ('[role="row"]:visible', "tbody tr:visible", ".ag-row:visible"):
            rows = page.locator(row_selector)
            extracted: list[dict[str, str]] = []
            for row_index in range(await rows.count()):
                cells = rows.nth(row_index).locator(
                    '[role="gridcell"]:visible, td:visible, .ag-cell:visible'
                )
                values: dict[str, str] = {}
                for cell_index in range(await cells.count()):
                    cell = cells.nth(cell_index)
                    text = (await cell.inner_text()).strip()
                    if not text:
                        continue
                    key = (
                        await cell.get_attribute("col-id")
                        or await cell.get_attribute("data-column")
                        or await cell.get_attribute("aria-colindex")
                        or f"column_{cell_index + 1}"
                    )
                    values[key] = text
                if len(values) >= 2:
                    extracted.append(values)
            if extracted:
                return extracted
        return []

    def _is_allowed_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == self._allowed_host or host.endswith(f".{self._allowed_host}")
