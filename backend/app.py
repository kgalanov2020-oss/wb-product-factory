from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status

from backend.config import get_settings
from backend.mpstats_collector.collector import PlaywrightMPStatsCollector
from backend.mpstats_collector.exceptions import MPStatsCollectorError
from backend.mpstats_collector.models import CollectionRequest, CollectionResult
from backend.mpstats_collector.repository import (
    NullCollectionRepository,
    SupabaseCollectionRepository,
)
from backend.mpstats_collector.service import MPStatsCollectorService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    repository = (
        SupabaseCollectionRepository.from_settings(settings)
        if settings.supabase_configured
        else NullCollectionRepository()
    )
    app.state.mpstats_service = MPStatsCollectorService(
        collector=PlaywrightMPStatsCollector(settings),
        repository=repository,
    )
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/mpstats/collect",
    response_model=CollectionResult,
    status_code=status.HTTP_201_CREATED,
    tags=["mpstats"],
)
async def collect_mpstats(
    payload: CollectionRequest,
    request: Request,
) -> CollectionResult:
    service: MPStatsCollectorService = request.app.state.mpstats_service
    try:
        return await service.collect(payload)
    except MPStatsCollectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

