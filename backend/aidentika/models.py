from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class AidentikaImageInput(BaseModel):
    url: HttpUrl | None = None
    data: str | None = None
    media_type: str | None = "image/jpeg"

    @model_validator(mode="after")
    def validate_source(self) -> "AidentikaImageInput":
        if not self.url and not self.data:
            raise ValueError("Either url or data is required")
        if self.url and self.data:
            raise ValueError("Use either url or data, not both")
        return self


class AidentikaAnalyzeRequest(BaseModel):
    image: AidentikaImageInput


class AidentikaPhotoGenerationRequest(BaseModel):
    images: list[AidentikaImageInput] = Field(min_length=1, max_length=5)
    category_id: str | None = None
    concept_id: str | None = None
    product_name: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=2_000)
    photo_style: Literal["classic", "flash"] = "classic"
    aspect_ratio: Literal["9:16", "4:3", "1:1", "16:9", "3:4"] = "3:4"
    webhook_url: HttpUrl | None = None
    project_id: int | None = None
    client_group_id: str | None = None


class AidentikaCardGenerationRequest(BaseModel):
    images: list[AidentikaImageInput] = Field(min_length=1, max_length=5)
    category_id: str | None = None
    concept_id: str | None = "infographic"
    product_name: str | None = Field(default=None, max_length=200)
    user_text: str | None = Field(default=None, max_length=5_000)
    design_key: str | None = None
    creativity: float = Field(default=0.5, ge=0.0, le=1.0)
    design_reference_image: AidentikaImageInput | None = None
    aspect_ratio: Literal["9:16", "4:3", "1:1", "16:9", "3:4"] = "3:4"
    style: Literal["classic", "premium"] = "classic"
    webhook_url: HttpUrl | None = None


class AidentikaActionResponse(BaseModel):
    action_id: int
    status: str
    poll_url: str | None = None
    project_id: int | None = None
    card_id: int | None = None
    detected: dict[str, Any] | None = None


class AidentikaStatusResponse(BaseModel):
    action_id: int
    status: str
    type: str | None = None
    result_url: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
