from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

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
    ProductContentRevisionRequest,
    ProductContentRequest,
    ProductContentStoredJob,
    RecommendedContentRequest,
    RecommendedContentResult,
    SupplierProductContentRequest,
    WBContentUploadResult,
)
from backend.product_content.exceptions import ProductContentRepositoryError
from backend.product_content.repository import (
    NullProductContentRepository,
    SupabaseProductContentRepository,
)
from backend.product_content.service import ProductContentService
from backend.supplier_products.exceptions import (
    SupplierPriceListError,
    SupplierProductRepositoryError,
)
from backend.supplier_products.models import (
    PriceListImportRequest,
    PriceListImportResult,
    ProductAnalysis,
    ProductListResponse,
    ProductStatsResponse,
    ProductStatus,
    SupplierProduct,
)
from backend.supplier_products.repository import (
    NullSupplierProductRepository,
    SupabaseSupplierProductRepository,
)
from backend.supplier_products.service import SupplierProductService

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
    app.state.supplier_product_repository = (
        SupabaseSupplierProductRepository.from_settings(settings)
        if settings.supabase_configured
        else NullSupplierProductRepository()
    )
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/integrations/health", tags=["system"])
async def integrations_health() -> dict[str, bool]:
    return {
        "supabase": settings.supabase_configured,
        "mpstats_login": settings.mpstats_login_configured,
        "mpstats_api": settings.mpstats_api_configured,
        "aidentika": settings.aidentika_configured,
        "openai": settings.openai_configured,
        "gemini": settings.gemini_configured,
        "wb_content": settings.wb_content_configured,
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
        settings=settings,
    )


def get_supplier_product_service(request: Request) -> SupplierProductService:
    return SupplierProductService(
        repository=request.app.state.supplier_product_repository,
        mpstats_service=request.app.state.mpstats_service,
        settings=settings,
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
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/api/v1/product-content/recommended/generate",
    response_model=RecommendedContentResult,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["product-content"],
)
async def generate_recommended_product_content(
    payload: RecommendedContentRequest,
    request: Request,
) -> RecommendedContentResult:
    try:
        return await get_product_content_service(request).generate_recommended(
            payload,
            request.app.state.supplier_product_repository,
        )
    except AidentikaConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/api/v1/product-content/supplier-products/{product_id}/generate",
    response_model=ProductContentJob,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["product-content"],
)
async def generate_supplier_product_content(
    product_id: UUID,
    payload: SupplierProductContentRequest,
    request: Request,
) -> ProductContentJob:
    try:
        return await get_product_content_service(request).generate_for_supplier_product(
            product_id,
            payload,
            request.app.state.supplier_product_repository,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AidentikaConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get(
    "/api/v1/product-content/jobs",
    response_model=list[ProductContentStoredJob],
    tags=["product-content"],
)
async def list_product_content_jobs(
    request: Request,
    limit: int = 20,
) -> list[ProductContentStoredJob]:
    try:
        return await get_product_content_service(request).list_jobs(limit=min(max(limit, 1), 100))
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get(
    "/api/v1/product-content/jobs/{job_id}",
    response_model=ProductContentStoredJob,
    tags=["product-content"],
)
async def get_product_content_job(
    job_id: UUID,
    request: Request,
) -> ProductContentStoredJob:
    try:
        job = await get_product_content_service(request).get_job(job_id)
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@app.post(
    "/api/v1/product-content/jobs/{job_id}/upload-wb",
    response_model=WBContentUploadResult,
    tags=["product-content"],
)
async def upload_product_content_to_wb(
    job_id: UUID,
    request: Request,
) -> WBContentUploadResult:
    try:
        return await get_product_content_service(request).upload_to_wb(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


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
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@app.post(
    "/api/v1/product-content/jobs/{job_id}/revise",
    response_model=ProductContentJob,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["product-content"],
)
async def revise_product_content_job(
    job_id: UUID,
    payload: ProductContentRevisionRequest,
    request: Request,
) -> ProductContentJob:
    try:
        return await get_product_content_service(request).revise_job(job_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AidentikaConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ProductContentRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AidentikaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/api/v1/supplier-products/import-url",
    response_model=PriceListImportResult,
    status_code=status.HTTP_201_CREATED,
    tags=["supplier-products"],
)
async def import_supplier_products_from_url(
    payload: PriceListImportRequest,
    request: Request,
) -> PriceListImportResult:
    try:
        return await get_supplier_product_service(request).import_from_url(
            str(payload.url),
            payload.supplier,
        )
    except SupplierPriceListError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post(
    "/api/v1/supplier-products/import-file",
    response_model=PriceListImportResult,
    status_code=status.HTTP_201_CREATED,
    tags=["supplier-products"],
)
async def import_supplier_products_from_file(
    request: Request,
    supplier: str = Form(default="zvezda"),
    file: UploadFile = File(...),
) -> PriceListImportResult:
    content = await file.read()
    try:
        return await get_supplier_product_service(request).import_from_file(
            content,
            file.filename or "price.csv",
            supplier,
        )
    except SupplierPriceListError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get(
    "/api/v1/supplier-products/stats",
    response_model=ProductStatsResponse,
    tags=["supplier-products"],
)
async def supplier_product_stats(request: Request) -> ProductStatsResponse:
    try:
        return await get_supplier_product_service(request).product_stats()
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get(
    "/api/v1/supplier-products",
    response_model=ProductListResponse,
    tags=["supplier-products"],
)
async def list_supplier_products(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
) -> ProductListResponse:
    try:
        return await get_supplier_product_service(request).list_products(
            limit=min(max(limit, 1), 200),
            offset=max(offset, 0),
            status=status_filter,
        )
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get(
    "/api/v1/supplier-products/recommendations",
    response_model=ProductListResponse,
    tags=["supplier-products"],
)
async def list_supplier_product_recommendations(
    request: Request,
    limit: int = 10,
    min_score: float = 0,
) -> ProductListResponse:
    try:
        products = await request.app.state.supplier_product_repository.list_recommended_products(
            limit=min(max(limit, 1), 50),
            min_score=max(min_score, 0),
        )
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return ProductListResponse(products=products, total=len(products))


@app.get(
    "/api/v1/supplier-products/{product_id}",
    response_model=SupplierProduct,
    tags=["supplier-products"],
)
async def get_supplier_product(
    product_id: UUID,
    request: Request,
) -> SupplierProduct:
    try:
        product = await get_supplier_product_service(request).get_product(product_id)
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@app.get(
    "/api/v1/supplier-products/{product_id}/analysis",
    response_model=ProductAnalysis,
    tags=["supplier-products"],
)
async def get_supplier_product_analysis(
    product_id: UUID,
    request: Request,
) -> ProductAnalysis:
    try:
        analysis = await get_supplier_product_service(request).get_analysis(product_id)
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis


@app.post(
    "/api/v1/supplier-products/{product_id}/analyze",
    response_model=ProductAnalysis,
    tags=["supplier-products"],
)
async def analyze_supplier_product(
    product_id: UUID,
    request: Request,
) -> ProductAnalysis:
    try:
        analysis = await get_supplier_product_service(request).analyze_product(product_id)
    except SupplierPriceListError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except MPStatsCollectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return analysis


@app.patch(
    "/api/v1/supplier-products/{product_id}/status",
    response_model=SupplierProduct,
    tags=["supplier-products"],
)
async def update_supplier_product_status(
    product_id: UUID,
    product_status: ProductStatus,
    request: Request,
) -> SupplierProduct:
    try:
        product = await get_supplier_product_service(request).update_status(product_id, product_status)
    except SupplierProductRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product
