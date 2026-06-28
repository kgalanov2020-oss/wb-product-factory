from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from supabase import Client, create_client

from backend.config import Settings

from .exceptions import ProductContentRepositoryError
from .models import (
    ProductContentAction,
    ProductContentJob,
    ProductContentJobStatus,
    ProductContentRequest,
    ProductContentStoredJob,
)


class ProductContentRepository(Protocol):
    async def save_job(self, request: ProductContentRequest, job: ProductContentJob) -> bool: ...

    async def get_job(self, job_id: UUID) -> ProductContentStoredJob | None: ...

    async def update_action(self, job_id: UUID, action: ProductContentAction) -> None: ...

    async def update_job_status(self, job_id: UUID, status: ProductContentJobStatus) -> None: ...


class NullProductContentRepository:
    async def save_job(self, request: ProductContentRequest, job: ProductContentJob) -> bool:
        return False

    async def get_job(self, job_id: UUID) -> ProductContentStoredJob | None:
        return None

    async def update_action(self, job_id: UUID, action: ProductContentAction) -> None:
        return None

    async def update_job_status(self, job_id: UUID, status: ProductContentJobStatus) -> None:
        return None


class SupabaseProductContentRepository:
    def __init__(self, client: Client, jobs_table: str, actions_table: str) -> None:
        self._client = client
        self._jobs_table = jobs_table
        self._actions_table = actions_table

    @classmethod
    def from_settings(cls, settings: Settings) -> SupabaseProductContentRepository:
        if not settings.supabase_configured:
            raise ValueError("Supabase is not configured")
        key = settings.supabase_service_role_key
        assert settings.supabase_url is not None and key is not None
        client = create_client(str(settings.supabase_url), key.get_secret_value())
        return cls(
            client,
            settings.supabase_product_content_jobs_table,
            settings.supabase_product_content_actions_table,
        )

    async def save_job(self, request: ProductContentRequest, job: ProductContentJob) -> bool:
        job_payload = {
            "id": str(job.job_id),
            "status": job.status,
            "product_name": job.product_name,
            "request_payload": request.model_dump(mode="json"),
        }
        action_payloads = [
            {
                "job_id": str(job.job_id),
                "asset_type": action.asset_type,
                "aidentika_action_id": action.action_id,
                "status": action.status,
                "poll_url": action.poll_url,
                "result_url": action.result_url,
                "error_message": action.error_message,
            }
            for action in job.actions
        ]

        def insert() -> None:
            self._client.table(self._jobs_table).insert(job_payload).execute()
            if action_payloads:
                self._client.table(self._actions_table).insert(action_payloads).execute()

        try:
            await asyncio.to_thread(insert)
        except Exception as exc:
            raise ProductContentRepositoryError(
                "Product content tables are unavailable. Apply supabase/schema.sql."
            ) from exc
        return True

    async def get_job(self, job_id: UUID) -> ProductContentStoredJob | None:
        def select() -> tuple[dict | None, list[dict]]:
            job_response = (
                self._client.table(self._jobs_table)
                .select("*")
                .eq("id", str(job_id))
                .maybe_single()
                .execute()
            )
            job_data = job_response.data
            if not job_data:
                return None, []
            actions_response = (
                self._client.table(self._actions_table)
                .select("*")
                .eq("job_id", str(job_id))
                .order("created_at")
                .execute()
            )
            return job_data, actions_response.data or []

        try:
            job_data, actions_data = await asyncio.to_thread(select)
        except Exception as exc:
            raise ProductContentRepositoryError(
                "Product content tables are unavailable. Apply supabase/schema.sql."
            ) from exc
        if not job_data:
            return None
        actions = [
            ProductContentAction(
                asset_type=action["asset_type"],
                action_id=action["aidentika_action_id"],
                status=action["status"],
                poll_url=action.get("poll_url"),
                result_url=action.get("result_url"),
                error_message=action.get("error_message"),
            )
            for action in actions_data
        ]
        return ProductContentStoredJob(
            job_id=job_data["id"],
            status=job_data["status"],
            product_name=job_data["product_name"],
            request_payload=job_data.get("request_payload") or {},
            actions=actions,
            created_at=job_data.get("created_at"),
            updated_at=job_data.get("updated_at"),
        )

    async def update_action(self, job_id: UUID, action: ProductContentAction) -> None:
        payload = {
            "status": action.status,
            "poll_url": action.poll_url,
            "result_url": action.result_url,
            "error_message": action.error_message,
        }
        try:
            await asyncio.to_thread(
                lambda: self._client.table(self._actions_table)
                .update(payload)
                .eq("job_id", str(job_id))
                .eq("aidentika_action_id", action.action_id)
                .execute()
            )
        except Exception as exc:
            raise ProductContentRepositoryError(
                "Product content tables are unavailable. Apply supabase/schema.sql."
            ) from exc

    async def update_job_status(self, job_id: UUID, status: ProductContentJobStatus) -> None:
        try:
            await asyncio.to_thread(
                lambda: self._client.table(self._jobs_table)
                .update({"status": status})
                .eq("id", str(job_id))
                .execute()
            )
        except Exception as exc:
            raise ProductContentRepositoryError(
                "Product content tables are unavailable. Apply supabase/schema.sql."
            ) from exc
