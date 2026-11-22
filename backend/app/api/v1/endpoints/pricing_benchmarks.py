"""
Pricing Benchmarks API Endpoints.
Provides market price benchmarking research, comparative analysis,
source evidence retrieval, and price refresh workflows for supplier raw materials.
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.models import Supplier, PriceResearchRun
from app.schemas.schemas import APIResponse, PricingResearchRequest
from app.services.pricing_research_service import (
    NoUsableMarketPricesError,
    pricing_research_service,
)

logger = logging.getLogger("pricing_benchmarks_api")

router = APIRouter()


@router.post("/{supplier_id}/pricing/research", response_model=APIResponse)
async def run_pricing_research(
    supplier_id: str,
    req: Optional[PricingResearchRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute real-time market price benchmarking research for a supplier's contracted material.
    Extracts contract specifications, searches web via Brave API, extracts B2B pricing,
    validates grades, normalizes currencies/units, calculates median benchmark, and generates AI insight.
    """
    region = req.region if req and req.region else "India"
    comparison_period = req.comparison_period if req and req.comparison_period else "Current Quarter"
    force_refresh = req.force_refresh if req and req.force_refresh else False

    try:
        # Check if recent research exists and force_refresh is not requested
        if not force_refresh:
            existing = await pricing_research_service.get_latest_analysis(db, supplier_id)
            if existing:
                return APIResponse(
                    status="success",
                    data=existing.model_dump(),
                    message="Retrieved existing market price benchmark analysis",
                )

        # Run fresh research
        result = await pricing_research_service.run_market_research(
            db=db,
            supplier_id=supplier_id,
            region=region,
            comparison_period=comparison_period,
            force_refresh=force_refresh,
        )
        return APIResponse(
            status="success",
            data=result.model_dump(),
            message="Market price research completed successfully",
        )
    except NoUsableMarketPricesError as exc:
        logger.info("Pricing research completed with no usable market prices for %s", supplier_id)
        raise HTTPException(status_code=422, detail="No usable market prices were found for this refresh.")
    except ValueError as ve:
        logger.warning(f"Pricing research validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("Market price research failed")
        raise HTTPException(status_code=500, detail="Market price research could not be completed. Please try again later.")


@router.get("/{supplier_id}/pricing/analysis", response_model=APIResponse)
async def get_pricing_analysis(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the latest market price benchmark analysis for a supplier.
    If no prior research exists, runs initial research automatically.
    """
    try:
        analysis = await pricing_research_service.get_latest_analysis(db, supplier_id)
        if not analysis:
            # Auto-run first research
            analysis = await pricing_research_service.run_market_research(db, supplier_id)

        return APIResponse(
            status="success",
            data=analysis.model_dump(),
            message="Market price benchmark retrieved successfully",
        )
    except NoUsableMarketPricesError:
        raise HTTPException(status_code=422, detail="No usable market prices were found for this refresh.")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("Failed to retrieve pricing analysis")
        raise HTTPException(status_code=500, detail="Market price analysis could not be retrieved. Please try again later.")


@router.get("/{supplier_id}/pricing/sources", response_model=APIResponse)
async def get_pricing_sources(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all market price research sources and observations for a supplier,
    including match classifications, raw prices, normalized prices, and clickable URLs.
    """
    analysis = await pricing_research_service.get_latest_analysis(db, supplier_id)
    if not analysis:
        return APIResponse(status="success", data=[], message="No research sources available yet")

    return APIResponse(
        status="success",
        data=[obs.model_dump() for obs in analysis.observations],
        message=f"Found {len(analysis.observations)} market price observation sources",
    )


@router.post("/{supplier_id}/pricing/refresh", response_model=APIResponse)
async def refresh_pricing_research(
    supplier_id: str,
    req: Optional[PricingResearchRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Force-refresh market price benchmarking research with new web discovery
    and updated exchange rates / market quotes.
    """
    region = req.region if req and req.region else "India"
    comparison_period = req.comparison_period if req and req.comparison_period else "Current Quarter"

    try:
        result = await pricing_research_service.run_market_research(
            db=db,
            supplier_id=supplier_id,
            region=region,
            comparison_period=comparison_period,
            force_refresh=True,
        )
        return APIResponse(
            status="success",
            data=result.model_dump(),
            message="Market price research refreshed successfully with new web observations",
        )
    except NoUsableMarketPricesError:
        raise HTTPException(status_code=422, detail="No usable market prices were found for this refresh.")
    except ValueError as ve:
        # A missing contract field is a client-data issue, not an internal
        # server failure. This also keeps refresh consistent with /research.
        logger.warning(f"Pricing refresh validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("Failed to refresh pricing research")
        raise HTTPException(status_code=500, detail="Market price refresh could not be completed. Please try again later.")
