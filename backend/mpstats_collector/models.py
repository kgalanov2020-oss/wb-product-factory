from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CollectionRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)


class MPStatsSnapshot(BaseModel):
    query: str
    collected_at: datetime
    niches: list[Any] = Field(default_factory=list)
    competitors: list[Any] = Field(default_factory=list)
    sales: list[Any] = Field(default_factory=list)
    prices: list[Any] = Field(default_factory=list)
    revenue: list[Any] = Field(default_factory=list)
    raw_payloads: list[dict[str, Any]] = Field(default_factory=list)


class CollectionResult(BaseModel):
    collection: MPStatsSnapshot
    persisted: bool
