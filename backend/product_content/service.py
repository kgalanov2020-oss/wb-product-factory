from __future__ import annotations

from uuid import UUID, uuid4

import httpx

from backend.aidentika.client import AidentikaClient
from backend.aidentika.exceptions import AidentikaConfigurationError
from backend.aidentika.models import (
    AidentikaCardGenerationRequest,
    AidentikaPhotoGenerationRequest,
)
from backend.aidentika.models import AidentikaStatusResponse
from backend.supplier_products.images import fetch_zvezda_product_images
from backend.supplier_products.repository import SupplierProductRepository

from .models import (
    ContentAssetType,
    ProductContentAction,
    ProductContentJob,
    ProductContentJobStatus,
    ProductContentRequest,
    ProductContentStoredJob,
    RecommendedContentRequest,
    RecommendedContentResult,
    RecommendedContentSkippedProduct,
    SupplierProductContentRequest,
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

    async def generate_recommended(
        self,
        request: RecommendedContentRequest,
        supplier_repository: SupplierProductRepository,
    ) -> RecommendedContentResult:
        if self._aidentika_client is None:
            raise AidentikaConfigurationError("Aidentika is not configured")

        products = await supplier_repository.list_recommended_products(
            limit=request.limit,
            min_score=request.min_score,
        )
        jobs: list[ProductContentJob] = []
        skipped: list[RecommendedContentSkippedProduct] = []
        for product in products:
            try:
                job = await self.generate_for_supplier_product(
                    product.id,
                    SupplierProductContentRequest(assets=request.assets),
                    supplier_repository,
                )
            except ValueError as exc:
                skipped.append(
                    RecommendedContentSkippedProduct(
                        product_id=product.id,
                        product_name=product.name,
                        reason=str(exc),
                    )
                )
                continue
            jobs.append(job)

        return RecommendedContentResult(
            requested=len(products),
            started=len(jobs),
            skipped=skipped,
            jobs=jobs,
        )

    async def generate_for_supplier_product(
        self,
        product_id: UUID,
        request: SupplierProductContentRequest,
        supplier_repository: SupplierProductRepository,
    ) -> ProductContentJob:
        if self._aidentika_client is None:
            raise AidentikaConfigurationError("Aidentika is not configured")
        product = await supplier_repository.get_product(product_id)
        if product is None:
            raise ValueError("Товар не найден")
        images = list(product.photo_urls)
        if not images and product.source_url:
            try:
                images = await fetch_zvezda_product_images(product.source_url)
            except httpx.HTTPError as exc:
                raise ValueError(f"Не удалось загрузить страницу с фото: {exc}") from exc
            if images:
                await supplier_repository.update_product_photos(product.id, images)
        if not images:
            raise ValueError("Не найдены исходные фото товара")

        analysis = await supplier_repository.get_analysis(product.id)
        content_request = ProductContentRequest(
            product_name=product.name,
            brand="Звезда",
            images=[{"url": image} for image in images[:5]],
            assets=request.assets,
            facts=_product_facts(product, analysis),
            target_audience="покупатели Wildberries, моделисты, родители, покупающие сборные модели и аксессуары",
        )
        job = await self.generate(content_request)
        await supplier_repository.update_product_status(product.id, "content_pending")
        return job

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


def _product_facts(product, analysis) -> list[str]:
    facts: list[str] = []
    if product.sku:
        facts.append(f"Артикул производителя: {product.sku}")
    if product.description:
        facts.append(f"Описание/размер из прайса: {product.description}")
    if product.dimensions:
        facts.append(f"Размер упаковки: {product.dimensions}")
    if product.weight_grams:
        facts.append(f"Вес: {product.weight_grams} г")
    if product.pack_units:
        facts.append(f"В коробке: {product.pack_units} шт.")
    if product.wholesale_price:
        facts.append(f"Закупочная цена: {product.wholesale_price} руб.")
    if analysis and analysis.market_price_avg:
        facts.append(f"Средняя цена рынка по MPStats: {analysis.market_price_avg} руб.")
    if analysis and analysis.competitor_count:
        facts.append(f"Найдено конкурентов по MPStats: {analysis.competitor_count}")
    if analysis and analysis.launch_score:
        facts.append(f"Score запуска: {analysis.launch_score}")
    return facts
