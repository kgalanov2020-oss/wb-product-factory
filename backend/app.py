from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, status

from backend.aidentika.client import AidentikaClient
from backend.aidentika.exceptions import AidentikaConfigurationError, AidentikaError
from backend.aidentika.models import (
    AidentikaActionResponse,
    AidentikaAnalyzeRequest,
    AidentikaCardGenerationRequest,
    AidentikaPhotoGenerationRequest,
    AidentikaStatusResponse,
)
from backend.config import get_settings
from backend.mpstats_collector.collector import PlaywrightMPStatsCollector
from backend.mpstats_collector.exceptions import MPStatsCollectorError
from backend.mpstats_collector.models import CollectionRequest, CollectionResult
from backend.mpstats_collector.repository import (
    NullCollectionRepository,
    SupabaseCollectionRepository,
)
from backend.mpstats_collector.service import MPStatsCollectorService
from backend.product_content.models import (
    ProductContentJob,
    ProductContentRequest,
    ProductContentStoredJob,
)
from backend.product_content.repository import (
    NullProductContentRepository,
    SupabaseProductContentRepository,
)
from backend.product_content.service import ProductContentService

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
    app.state.aidentika_client = (
        AidentikaClient(settings) if settings.aidentika_configured else None
    )
    app.state.product_content_repository = (
        SupabaseProductContentRepository.from_settings(settings)
        if settings.supabase_configured
        else NullProductContentRepository()
    )
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/integrations/health", tags=["system"])
async def integrations_health() -> dict[str, bool]:
    return {
        "supabase": settings.supabase_configured,
        "mpstats_login": settings.mpstats_login_configured,
        "aidentika": settings.aidentika_configured,
    }


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


def get_aidentika_client(request: Request) -> AidentikaClient:
    client = request.app.state.aidentika_client
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Aidentika is not configured",
        )
    return client


def get_product_content_service(request: Request) -> ProductContentService:
    return ProductContentService(
        aidentika_client=request.app.state.aidentika_client,
        repository=request.app.state.product_content_repository,
    )


@app.post(
    "/api/v1/aidentika/analyze",
    tags=["aidentika"],
)
async def analyze_aidentika_image(
    payload: AidentikaAnalyzeRequest,
    request: Request,
) -> dict:
    try:
        return await get_aidentika_client(request).analyze(payload)
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/api/v1/aidentika/generate/photo",
    response_model=AidentikaActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["aidentika"],
)
async def generate_aidentika_photo(
    payload: AidentikaPhotoGenerationRequest,
    request: Request,
) -> AidentikaActionResponse:
    try:
        return await get_aidentika_client(request).generate_photo(payload)
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/api/v1/aidentika/generate/card",
    response_model=AidentikaActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["aidentika"],
)
async def generate_aidentika_card(
    payload: AidentikaCardGenerationRequest,
    request: Request,
) -> AidentikaActionResponse:
    try:
        return await get_aidentika_client(request).generate_card(payload)
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get(
    "/api/v1/aidentika/status/{action_id}",
    response_model=AidentikaStatusResponse,
    tags=["aidentika"],
)
async def get_aidentika_status(
    action_id: int,
    request: Request,
) -> AidentikaStatusResponse:
    try:
        return await get_aidentika_client(request).get_status(action_id)
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/api/v1/product-content/generate",
    response_model=ProductContentJob,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["product-content"],
)
async def generate_product_content(
    payload: ProductContentRequest,
    request: Request,
) -> ProductContentJob:
    service = get_product_content_service(request)
    try:
        return await service.generate(payload)
    except AidentikaConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get(
    "/api/v1/product-content/jobs/{job_id}",
    response_model=ProductContentStoredJob,
    tags=["product-content"],
)
async def get_product_content_job(
    job_id: UUID,
    request: Request,
) -> ProductContentStoredJob:
    job = await get_product_content_service(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@app.post(
    "/api/v1/product-content/jobs/{job_id}/sync",
    response_model=ProductContentStoredJob,
    tags=["product-content"],
)
async def sync_product_content_job(
    job_id: UUID,
    request: Request,
) -> ProductContentStoredJob:
    try:
        job = await get_product_content_service(request).sync_job(job_id)
    except AidentikaConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
