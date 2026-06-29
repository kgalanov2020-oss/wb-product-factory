from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from backend.aidentika.models import AidentikaImageInput


ContentAssetType = Literal[
    "main_photo",
    "infographic",
    "advantages",
    "usage",
    "comparison",
]
ProductContentJobStatus = Literal["queued", "running", "completed", "failed", "partial"]


class ProductContentRequest(BaseModel):
    product_name: str = Field(min_length=2, max_length=200)
    images: list[AidentikaImageInput] = Field(min_length=1, max_length=5)
    category_id: str | None = None
    brand: str | None = Field(default=None, max_length=100)
    marketplace: Literal["wildberries"] = "wildberries"
    assets: list[ContentAssetType] = Field(
        default_factory=lambda: ["main_photo", "infographic", "advantages"]
    )
    facts: list[str] = Field(default_factory=list, max_length=20)
    target_audience: str | None = Field(default=None, max_length=300)
    reference_image: AidentikaImageInput | None = None
    webhook_url: HttpUrl | None = None
    card_draft: dict[str, Any] = Field(default_factory=dict)


class ProductContentAction(BaseModel):
    asset_type: ContentAssetType
    action_id: int
    status: str
    poll_url: str | None = None
    result_url: str | None = None
    error_message: str | None = None


class ProductContentJob(BaseModel):
    job_id: UUID
    status: ProductContentJobStatus
    product_name: str
    actions: list[ProductContentAction]
    persisted: bool = False


class ProductContentStoredJob(BaseModel):
    job_id: UUID
    status: ProductContentJobStatus
    product_name: str
    request_payload: dict[str, Any]
    actions: list[ProductContentAction]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RecommendedContentRequest(BaseModel):
    limit: int = Field(default=3, ge=1, le=20)
    min_score: float = Field(default=50, ge=0, le=100)
    assets: list[ContentAssetType] = Field(
        default_factory=lambda: ["main_photo", "infographic", "advantages", "usage"]
    )


class SupplierProductContentRequest(BaseModel):
    assets: list[ContentAssetType] = Field(
        default_factory=lambda: ["main_photo", "infographic", "advantages", "usage"]
    )


class RecommendedContentSkippedProduct(BaseModel):
    product_id: UUID
    product_name: str
    reason: str


class RecommendedContentResult(BaseModel):
    requested: int
    started: int
    skipped: list[RecommendedContentSkippedProduct] = Field(default_factory=list)
    jobs: list[ProductContentJob] = Field(default_factory=list)


class WBContentUploadResult(BaseModel):
    status: Literal["uploaded", "not_configured", "not_ready"]
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
