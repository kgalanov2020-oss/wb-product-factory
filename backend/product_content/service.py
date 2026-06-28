from __future__ import annotations

from uuid import UUID, uuid4

from backend.aidentika.client import AidentikaClient
from backend.aidentika.exceptions import AidentikaConfigurationError
from backend.aidentika.models import (
    AidentikaCardGenerationRequest,
    AidentikaPhotoGenerationRequest,
)
from backend.aidentika.models import AidentikaStatusResponse

from .models import (
    ContentAssetType,
    ProductContentAction,
    ProductContentJob,
    ProductContentJobStatus,
    ProductContentRequest,
    ProductContentStoredJob,
)
from .repository import ProductContentRepository


class ProductContentService:
    def __init__(
        self,
        aidentika_client: AidentikaClient | None,
        repository: ProductContentRepository,
    ) -> None:
        self._aidentika_client = aidentika_client
        self._repository = repository

    async def generate(self, request: ProductContentRequest) -> ProductContentJob:
        if self._aidentika_client is None:
            raise AidentikaConfigurationError("Aidentika is not configured")
        job_id = uuid4()
        actions: list[ProductContentAction] = []

        for asset_type in request.assets:
            idempotency_key = f"wb-product-content:{job_id}:{asset_type}"
            if asset_type == "main_photo":
                response = await self._aidentika_client.generate_photo(
                    AidentikaPhotoGenerationRequest(
                        images=request.images,
                        category_id=request.category_id,
                        concept_id="product_photo",
                        product_name=request.product_name,
                        comment=self._build_prompt(request, asset_type),
                        aspect_ratio="3:4",
                        webhook_url=request.webhook_url,
                    ),
                    idempotency_key=idempotency_key,
                )
            else:
                response = await self._aidentika_client.generate_card(
                    AidentikaCardGenerationRequest(
                        images=request.images,
                        category_id=request.category_id,
                        concept_id=self._concept_id(asset_type),
                        product_name=request.product_name,
                        user_text=self._build_prompt(request, asset_type),
                        design_reference_image=request.reference_image,
                        aspect_ratio="3:4",
                        style="classic",
                        webhook_url=request.webhook_url,
                    ),
                    idempotency_key=idempotency_key,
                )
            actions.append(
                ProductContentAction(
                    asset_type=asset_type,
                    action_id=response.action_id,
                    status=response.status,
                    poll_url=response.poll_url,
                )
            )

        job = ProductContentJob(
            job_id=job_id,
            status="queued",
            product_name=request.product_name,
            actions=actions,
        )
        job.persisted = await self._repository.save_job(request, job)
        return job

    async def get_job(self, job_id: UUID) -> ProductContentStoredJob | None:
        return await self._repository.get_job(job_id)

    async def sync_job(self, job_id: UUID) -> ProductContentStoredJob | None:
        if self._aidentika_client is None:
            raise AidentikaConfigurationError("Aidentika is not configured")
        job = await self._repository.get_job(job_id)
        if job is None:
            return None

        synced_actions: list[ProductContentAction] = []
        for action in job.actions:
            status = await self._aidentika_client.get_status(action.action_id)
            synced_action = self._from_status(action, status)
            await self._repository.update_action(job_id, synced_action)
            synced_actions.append(synced_action)

        job_status = self._job_status(synced_actions)
        await self._repository.update_job_status(job_id, job_status)
        refreshed = await self._repository.get_job(job_id)
        if refreshed:
            return refreshed
        fallback = job.model_dump()
        fallback["status"] = job_status
        fallback["actions"] = synced_actions
        return ProductContentStoredJob.model_validate(fallback)

    @staticmethod
    def _from_status(
        action: ProductContentAction,
        status: AidentikaStatusResponse,
    ) -> ProductContentAction:
        return ProductContentAction(
            asset_type=action.asset_type,
            action_id=action.action_id,
            status=status.status,
            poll_url=action.poll_url,
            result_url=status.result_url,
            error_message=status.error_message,
        )

    @staticmethod
    def _job_status(actions: list[ProductContentAction]) -> ProductContentJobStatus:
        statuses = {action.status.lower() for action in actions}
        if not statuses:
            return "queued"
        if any(status in statuses for status in ("failed", "error")):
            if any(status in statuses for status in ("completed", "done", "success")):
                return "partial"
            return "failed"
        if statuses <= {"completed", "done", "success"}:
            return "completed"
        if any(status in statuses for status in ("running", "processing", "in_progress")):
            return "running"
        return "queued"

    @staticmethod
    def _concept_id(asset_type: ContentAssetType) -> str:
        concepts = {
            "infographic": "infographic",
            "advantages": "infographic",
            "usage": "infographic",
            "comparison": "infographic",
            "main_photo": "product_photo",
        }
        return concepts[asset_type]

    @staticmethod
    def _build_prompt(request: ProductContentRequest, asset_type: ContentAssetType) -> str:
        facts = "; ".join(request.facts) if request.facts else "нет дополнительных фактов"
        brand = request.brand or "бренд не указан"
        audience = request.target_audience or "покупатели Wildberries"
        base = (
            f"Товар: {request.product_name}. Бренд: {brand}. "
            f"Площадка: Wildberries. Целевая аудитория: {audience}. "
            f"Факты о товаре: {facts}."
        )
        instructions = {
            "main_photo": (
                "Сделай чистое продающее главное фото товара для Wildberries: "
                "товар должен быть главным объектом, фон аккуратный, без лишнего текста."
            ),
            "infographic": (
                "Сделай инфографику для карточки Wildberries: 3-5 коротких выгод, "
                "крупный товар, читабельные подписи, без выдуманных характеристик."
            ),
            "advantages": (
                "Сделай слайд с преимуществами товара: короткие тезисы, понятные иконки, "
                "акцент на практической пользе для покупателя."
            ),
            "usage": (
                "Сделай слайд со способом применения товара: простая последовательность шагов, "
                "понятная визуальная подача, без медицинских или неподтвержденных обещаний."
            ),
            "comparison": (
                "Сделай сравнительный слайд: покажи, чем товар отличается от типовых аналогов, "
                "используй только безопасные формулировки без упоминания конкретных конкурентов."
            ),
        }
        return f"{base} {instructions[asset_type]}"
