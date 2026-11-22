
"""Market benchmark refresh, history and verified price import endpoints."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import MarketPriceBenchmark
from app.services.market_price_service import (
    API_KEY_MISSING,
    import_supplier_catalogue,
    import_supplier_quotation,
    refresh_raw_material_benchmarks,
)
from app.services.sql_retriever import sql_retriever
from app.schemas.schemas import APIResponse


router = APIRouter()


class QuotationImport(BaseModel):
    product_name: str
    category: str | None = None
    product_specification: str
    price: str
    currency: str
    unit: str
    source_name: str = "Supplier quotation"
    source_url: str = ""
    verified: bool = False


def _serialize(benchmark: MarketPriceBenchmark) -> dict:
    return {
        "benchmark_id": benchmark.benchmark_id,
        "product_id": benchmark.product_id,
        "product_name": (
            benchmark.product.product_name if benchmark.product else None
        ),
        "category": (
            benchmark.product.category if benchmark.product else None
        ),
        "price": str(benchmark.benchmark_price),
        "currency": benchmark.currency,
        "unit": benchmark.unit,
        "source": benchmark.source_name,
        "source_url": benchmark.source_url,
        "type": benchmark.benchmark_type,
        "date": benchmark.benchmark_date.isoformat(),
        "retrieved_at": (
            benchmark.retrieved_at.isoformat()
            if benchmark.retrieved_at
            else None
        ),
        "verification_status": benchmark.verification_status,
        "product_specification": benchmark.product_specification,
        "metal_symbol": benchmark.metal_symbol,
    }


async def _load_with_products(
    db: AsyncSession,
    benchmarks: list[MarketPriceBenchmark],
) -> list[MarketPriceBenchmark]:
    """Reload benchmarks with their related products eagerly loaded."""

    benchmark_ids = [b.benchmark_id for b in benchmarks]

    if not benchmark_ids:
        return []

    result = await db.execute(
        select(MarketPriceBenchmark)
        .options(selectinload(MarketPriceBenchmark.product))
        .where(MarketPriceBenchmark.benchmark_id.in_(benchmark_ids))
    )

    loaded = {
        b.benchmark_id: b
        for b in result.scalars().all()
    }

    return [
        loaded[benchmark_id]
        for benchmark_id in benchmark_ids
        if benchmark_id in loaded
    ]


@router.post("/refresh/raw-materials", response_model=APIResponse)
async def refresh_prices(db: AsyncSession = Depends(get_db)):
    try:
        saved = await refresh_raw_material_benchmarks(db)
        saved = await _load_with_products(db, saved)

    except ValueError as exc:
        status = (
            "not_configured"
            if str(exc) == API_KEY_MISSING
            else "error"
        )
        return APIResponse(status=status, message=str(exc))

    return APIResponse(
        status="success",
        data=[_serialize(b) for b in saved],
    )


@router.get("/latest", response_model=APIResponse)
async def latest_prices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MarketPriceBenchmark)
        .options(selectinload(MarketPriceBenchmark.product))
        .where(MarketPriceBenchmark.is_demo.is_(False))
        .order_by(
            MarketPriceBenchmark.benchmark_date.desc(),
            MarketPriceBenchmark.retrieved_at.desc(),
        )
    )

    return APIResponse(
        data=[_serialize(b) for b in result.scalars().all()]
    )


@router.get("/history/{product_id}", response_model=APIResponse)
async def price_history(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MarketPriceBenchmark)
        .options(selectinload(MarketPriceBenchmark.product))
        .where(MarketPriceBenchmark.product_id == product_id)
        .order_by(MarketPriceBenchmark.benchmark_date.desc())
    )

    return APIResponse(
        data=[_serialize(b) for b in result.scalars().all()]
    )


@router.post("/quotations/import", response_model=APIResponse)
async def import_quotations(
    payload: list[QuotationImport],
    db: AsyncSession = Depends(get_db),
):
    try:
        saved = await import_supplier_quotation(
            db,
            [item.model_dump() for item in payload],
        )
        saved = await _load_with_products(db, saved)

    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return APIResponse(
        data=[_serialize(b) for b in saved]
    )


@router.post("/catalogues/import", response_model=APIResponse)
async def import_catalogue(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="Catalogue file exceeds 10 MB.",
        )

    try:
        saved = await import_supplier_catalogue(
            db,
            content,
            file.filename or "",
        )
        saved = await _load_with_products(db, saved)

    except (ValueError, TypeError, ImportError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return APIResponse(
        data=[_serialize(b) for b in saved]
    )


@router.get(
    "/comparisons/suppliers/{supplier_id}",
    response_model=APIResponse,
)
async def supplier_price_comparisons(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
):
    return APIResponse(
        data=await sql_retriever.get_price_comparison(
            db,
            supplier_id,
        )
    )
