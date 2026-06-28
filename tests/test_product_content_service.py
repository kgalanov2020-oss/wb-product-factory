from __future__ import annotations

from uuid import UUID

import pytest

from backend.aidentika.models import AidentikaActionResponse, AidentikaStatusResponse
from backend.product_content.models import (
    ProductContentAction,
    ProductContentJob,
    ProductContentRequest,
    ProductContentStoredJob,
)
from backend.product_content.service import ProductContentService


class FakeAidentikaClient:
    def __init__(self) -> None:
        self.photo_requests = []
        self.card_requests = []

    async def generate_photo(self, request, idempotency_key=None):
        self.photo_requests.append((request, idempotency_key))
        return AidentikaActionResponse(action_id=101, status="queued")

    async def generate_card(self, request, idempotency_key=None):
        action_id = 200 + len(self.card_requests)
        self.card_requests.append((request, idempotency_key))
        return AidentikaActionResponse(action_id=action_id, status="queued")

    async def get_status(self, action_id: int):
        status = "completed" if action_id == 101 else "running"
        return AidentikaStatusResponse(
            action_id=action_id,
            status=status,
            result_url=f"https://example.com/{action_id}.png" if status == "completed" else None,
            raw={},
        )


class FakeRepository:
    def __init__(self) -> None:
        self.job: ProductContentStoredJob | None = None

    async def save_job(self, request: ProductContentRequest, job: ProductContentJob) -> bool:
        self.job = ProductContentStoredJob(
            job_id=job.job_id,
            status=job.status,
            product_name=job.product_name,
            request_payload=request.model_dump(mode="json"),
            actions=job.actions,
        )
        return True

    async def get_job(self, job_id: UUID):
        return self.job if self.job and self.job.job_id == job_id else None

    async def update_action(self, job_id: UUID, action: ProductContentAction) -> None:
        assert self.job is not None
        self.job.actions = [
            action if existing.action_id == action.action_id else existing
            for existing in self.job.actions
        ]

    async def update_job_status(self, job_id: UUID, status: str) -> None:
        assert self.job is not None
        self.job.status = status


@pytest.mark.asyncio
async def test_generate_product_content_starts_expected_aidentika_actions():
    client = FakeAidentikaClient()
    repository = FakeRepository()
    service = ProductContentService(client, repository)

    job = await service.generate(
        ProductContentRequest(
            product_name="Клей Звезда",
            images=[{"url": "https://example.com/product.jpg"}],
            assets=["main_photo", "infographic", "advantages"],
        )
    )

    assert job.persisted is True
    assert job.status == "queued"
    assert [action.asset_type for action in job.actions] == [
        "main_photo",
        "infographic",
        "advantages",
    ]
    assert len(client.photo_requests) == 1
    assert len(client.card_requests) == 2


@pytest.mark.asyncio
async def test_sync_product_content_job_updates_actions_and_job_status():
    client = FakeAidentikaClient()
    repository = FakeRepository()
    service = ProductContentService(client, repository)
    job = await service.generate(
        ProductContentRequest(
            product_name="Клей Звезда",
            images=[{"url": "https://example.com/product.jpg"}],
            assets=["main_photo", "infographic"],
        )
    )

    synced = await service.sync_job(job.job_id)

    assert synced is not None
    assert synced.status == "running"
    assert synced.actions[0].status == "completed"
    assert synced.actions[0].result_url == "https://example.com/101.png"
