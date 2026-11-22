"""
Pricing Research Orchestration Service.
Coordinates:
1. Active contract & specification extraction
2. Brave Search web discovery
3. Webpage pricing extraction
4. Material specification matching & validation
5. Multi-currency and unit normalization
6. Median market benchmark calculation
7. AI executive procurement insights
8. Relational persistence in PostgreSQL
"""

import uuid
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.models.models import PriceResearchRun, MarketPriceObservation, Supplier, Contract
from app.core.config import settings
from app.schemas.schemas import (
    ContractPricingDetails,
    MarketPriceObservationSchema,
    PriceBenchmarkResponse,
    PricingInsightSchema,
)
from app.services.contract_pricing_extractor import contract_pricing_extractor
from app.services.brave_search_service import brave_search_service
from app.services.webpage_extraction_service import webpage_extraction_service
from app.services.material_matching_service import material_matching_service
from app.services.price_normalization_service import price_normalization_service
from app.services.price_benchmark_service import price_benchmark_service
from app.services.pricing_insight_service import pricing_insight_service

logger = logging.getLogger("pricing_research_service")


class NoUsableMarketPricesError(ValueError):
    """Raised only after every discovered source has been safely rejected."""


class PricingResearchService:
    """End-to-end coordinator for market price benchmarking research."""

    async def run_market_research(
        self,
        db: AsyncSession,
        supplier_id: str,
        region: str = "India",
        comparison_period: str = "Current Quarter",
        force_refresh: bool = False,
    ) -> PriceBenchmarkResponse:
        """
        Executes full market benchmarking workflow for a supplier's contracted material.
        Saves research run and observation records to PostgreSQL.
        """
        # Step 1: Extract Contract Details
        contract_details = await contract_pricing_extractor.extract_pricing_details(db, supplier_id)
        if not contract_details or contract_details.contract_unit_price <= 0:
            raise ValueError(f"Could not extract contracted price for supplier {supplier_id}")

        # Step 2: Web Discovery via Brave Search API
        search_hits = await brave_search_service.search_market_prices(
            contract=contract_details,
            region=region,
        )

        # Step 3 & 4: Extract and Normalize Observations concurrently
        import asyncio

        semaphore = asyncio.Semaphore(5)
        skipped_sources: List[Dict[str, str]] = []

        async def process_hit(hit):
            async with semaphore:
                record = await webpage_extraction_service.extract_record_from_source(hit, contract_details)
                if not record or record.get("raw_price") is None or record["raw_price"] <= 0:
                    skipped_sources.append({
                        "url": str(hit.get("url") or ""),
                        "reason": str(hit.get("_pricing_skip_reason") or "no verifiable positive price"),
                    })
                    return None

                # Material matching & classification
                match_class, match_rationale, is_included = material_matching_service.evaluate_match(
                    observation=record,
                    contract=contract_details,
                )

                # Price Normalization
                norm_price, fx_rate, unit_ratio, norm_note = price_normalization_service.normalize(
                    raw_price=record["raw_price"],
                    raw_currency=record["raw_currency"],
                    raw_unit=record["raw_unit"],
                    contract=contract_details,
                    observation=record,
                )

                if not norm_price or norm_price <= 0:
                    skipped_sources.append({
                        "url": str(record.get("source_url") or ""),
                        "reason": f"normalization: {norm_note}",
                    })
                    return None

                obs_id = f"OBS-{uuid.uuid4().hex[:8].upper()}"
                return {
                    "id": obs_id,
                    "source_name": record.get("source_name") or "Market Source",
                    "source_url": record.get("source_url") or "",
                    "material_name": record.get("material_name") or contract_details.material_name,
                    "grade": record.get("grade") or contract_details.grade,
                    "specification": record.get("specification"),
                    "raw_price": record.get("raw_price"),
                    "raw_currency": record.get("raw_currency"),
                    "raw_unit": record.get("raw_unit"),
                    "normalized_price": norm_price,
                    "normalized_currency": contract_details.currency,
                    "normalized_unit": contract_details.unit_of_measurement,
                    "exchange_rate_applied": fx_rate,
                    "unit_conversion_ratio": unit_ratio,
                    "location": record.get("location") or region,
                    "observation_date": record.get("observation_date") or datetime.now().strftime("%Y-%m-%d"),
                    "price_type": record.get("price_type") or "supplier offer",
                    "delivery_conditions": record.get("delivery_conditions") or "Unspecified",
                    "tax_inclusion": record.get("tax_inclusion") or "Excl. Tax",
                    "match_classification": match_class,
                    "match_rationale": f"{match_rationale} ({norm_note})",
                    "snippet": record.get("snippet"),
                    "is_included_in_benchmark": is_included,
                    "retrieved_at": datetime.now().isoformat(),
                }

        results = await asyncio.gather(*[process_hit(hit) for hit in search_hits])
        raw_observations = [r for r in results if r is not None]
        if not raw_observations:
            reasons = "; ".join(item["reason"] for item in skipped_sources[:3])
            logger.warning(
                "No usable market prices for supplier %s. candidates=%d skipped=%d reasons=%s",
                supplier_id,
                len(search_hits),
                len(skipped_sources),
                reasons or "no live search results",
            )
            raise NoUsableMarketPricesError(
                "No verifiable market prices were found. "
                "Sources without a positive price, currency, unit, or compatible normalization were skipped."
            )
        observation_schemas = [MarketPriceObservationSchema(**obs) for obs in raw_observations]

        # Step 5: Statistical Benchmark Calculation
        benchmark = price_benchmark_service.compute_benchmark(contract_details, observation_schemas)

        # Step 6: AI Executive Procurement Insight
        ai_insight = await pricing_insight_service.generate_insight(
            contract=contract_details,
            benchmark=benchmark,
            observations=observation_schemas,
        )

        # Step 7: Historical Trend Observation Points
        historical_trend = self._generate_historical_trend(contract_details, benchmark, observation_schemas)

        # Step 8: Database Persistence in PostgreSQL
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        run_record = PriceResearchRun(
            id=run_id,
            supplier_id=supplier_id,
            contract_id=contract_details.contract_id,
            material_name=contract_details.material_name,
            grade=contract_details.grade,
            product_code=contract_details.product_code,
            technical_characteristics=contract_details.technical_characteristics,
            contract_price=Decimal(str(contract_details.contract_unit_price)),
            contract_currency=contract_details.currency,
            contract_unit=contract_details.unit_of_measurement,
            contract_quantity=Decimal(str(contract_details.contract_quantity)) if contract_details.contract_quantity else None,
            annual_quantity=Decimal(str(contract_details.annual_estimated_quantity)) if contract_details.annual_estimated_quantity else None,
            delivery_terms=contract_details.incoterms,
            delivery_location=contract_details.delivery_location,
            tax_terms=contract_details.tax_inclusion,
            packaging_details=contract_details.packaging_details,
            region=region,
            comparison_period=comparison_period,
            market_benchmark_median=Decimal(str(benchmark["market_benchmark_median"])) if benchmark.get("market_benchmark_median") else None,
            market_min_price=Decimal(str(benchmark["market_min_price"])) if benchmark.get("market_min_price") else None,
            market_max_price=Decimal(str(benchmark["market_max_price"])) if benchmark.get("market_max_price") else None,
            market_avg_price=Decimal(str(benchmark["market_avg_price"])) if benchmark.get("market_avg_price") else None,
            variance_pct=Decimal(str(benchmark["variance_pct"])) if benchmark.get("variance_pct") is not None else None,
            potential_annual_difference=Decimal(str(benchmark["potential_annual_difference"])) if benchmark.get("potential_annual_difference") is not None else None,
            confidence_score=Decimal(str(benchmark["confidence_score"])) if benchmark.get("confidence_score") is not None else None,
            confidence_level=benchmark.get("confidence_level"),
            ai_summary=ai_insight.summary,
            ai_insight=ai_insight.model_dump(),
            status="completed",
        )
        db.add(run_record)
        await db.flush()

        for obs in raw_observations:
            obs_db = MarketPriceObservation(
                id=obs["id"],
                research_run_id=run_id,
                source_name=obs["source_name"],
                source_url=obs["source_url"],
                material_name=obs["material_name"],
                grade=obs["grade"],
                specification=obs["specification"],
                raw_price=Decimal(str(obs["raw_price"])) if obs["raw_price"] is not None else None,
                raw_currency=obs["raw_currency"],
                raw_unit=obs["raw_unit"],
                normalized_price=Decimal(str(obs["normalized_price"])),
                normalized_currency=obs["normalized_currency"],
                normalized_unit=obs["normalized_unit"],
                exchange_rate_applied=Decimal(str(obs["exchange_rate_applied"])) if obs["exchange_rate_applied"] is not None else None,
                unit_conversion_ratio=Decimal(str(obs["unit_conversion_ratio"])) if obs["unit_conversion_ratio"] is not None else None,
                location=obs["location"],
                observation_date=datetime.strptime(obs["observation_date"], "%Y-%m-%d").date() if obs.get("observation_date") else None,
                price_type=obs["price_type"],
                delivery_conditions=obs["delivery_conditions"],
                tax_inclusion=obs["tax_inclusion"],
                match_classification=obs["match_classification"],
                match_rationale=obs["match_rationale"],
                snippet=obs["snippet"],
                is_included_in_benchmark=obs["is_included_in_benchmark"],
            )
            db.add(obs_db)

        await db.commit()

        return PriceBenchmarkResponse(
            research_run_id=run_id,
            supplier_id=supplier_id,
            supplier_name=contract_details.supplier_name or supplier_id,
            contract_details=contract_details,
            market_benchmark_median=benchmark.get("market_benchmark_median"),
            market_min_price=benchmark.get("market_min_price"),
            market_max_price=benchmark.get("market_max_price"),
            market_avg_price=benchmark.get("market_avg_price"),
            variance_pct=benchmark.get("variance_pct"),
            potential_annual_difference=benchmark.get("potential_annual_difference"),
            confidence_score=benchmark.get("confidence_score"),
            confidence_level=benchmark.get("confidence_level") or "Moderate",
            observations=observation_schemas,
            historical_trend=historical_trend,
            ai_insight=ai_insight,
            created_at=datetime.now().isoformat(),
            status="completed",
            research_notice=(
                "Live market-source search is not configured. Add TAVILY_API_KEY to enable verifiable price research."
                if not raw_observations and not (settings.TAVILY_API_KEY or settings.BRAVE_SEARCH_API_KEY)
                else None
            ),
        )

    async def get_latest_analysis(
        self,
        db: AsyncSession,
        supplier_id: str,
    ) -> Optional[PriceBenchmarkResponse]:
        """Fetch the most recent market price benchmark research run from database."""
        stmt = (
            select(PriceResearchRun)
            .where(PriceResearchRun.supplier_id == supplier_id)
            .options(selectinload(PriceResearchRun.observations))
            .order_by(PriceResearchRun.created_at.desc())
        )
        res = await db.execute(stmt)
        run = res.scalars().first()
        if not run:
            return None

        # Build contract details
        contract_details = ContractPricingDetails(
            material_name=run.material_name,
            grade=run.grade,
            product_code=run.product_code,
            technical_characteristics=run.technical_characteristics,
            contract_unit_price=float(run.contract_price),
            currency=run.contract_currency,
            unit_of_measurement=run.contract_unit,
            contract_quantity=float(run.contract_quantity) if run.contract_quantity else None,
            annual_estimated_quantity=float(run.annual_quantity) if run.annual_quantity else None,
            delivery_location=run.delivery_location,
            incoterms=run.delivery_terms,
            tax_inclusion=run.tax_terms,
            packaging_details=run.packaging_details,
            supplier_name=supplier_id,
            contract_id=run.contract_id,
        )

        obs_schemas = [
            MarketPriceObservationSchema(
                id=o.id,
                source_name=o.source_name,
                source_url=o.source_url,
                material_name=o.material_name,
                grade=o.grade,
                specification=o.specification,
                raw_price=float(o.raw_price) if o.raw_price else None,
                raw_currency=o.raw_currency,
                raw_unit=o.raw_unit,
                normalized_price=float(o.normalized_price),
                normalized_currency=o.normalized_currency,
                normalized_unit=o.normalized_unit,
                exchange_rate_applied=float(o.exchange_rate_applied) if o.exchange_rate_applied else None,
                unit_conversion_ratio=float(o.unit_conversion_ratio) if o.unit_conversion_ratio else None,
                location=o.location,
                observation_date=o.observation_date.isoformat() if o.observation_date else None,
                price_type=o.price_type,
                delivery_conditions=o.delivery_conditions,
                tax_inclusion=o.tax_inclusion,
                match_classification=o.match_classification,
                match_rationale=o.match_rationale,
                snippet=o.snippet,
                is_included_in_benchmark=o.is_included_in_benchmark,
                retrieved_at=o.retrieved_at.isoformat() if o.retrieved_at else None,
            )
            for o in run.observations
        ]

        historical_trend = self._generate_historical_trend(
            contract_details,
            {"market_benchmark_median": float(run.market_benchmark_median) if run.market_benchmark_median else None},
            obs_schemas,
        )

        ai_insight = None
        if run.ai_insight:
            ai_insight = PricingInsightSchema(**run.ai_insight)

        return PriceBenchmarkResponse(
            research_run_id=run.id,
            supplier_id=supplier_id,
            supplier_name=contract_details.supplier_name or supplier_id,
            contract_details=contract_details,
            market_benchmark_median=float(run.market_benchmark_median) if run.market_benchmark_median else None,
            market_min_price=float(run.market_min_price) if run.market_min_price else None,
            market_max_price=float(run.market_max_price) if run.market_max_price else None,
            market_avg_price=float(run.market_avg_price) if run.market_avg_price else None,
            variance_pct=float(run.variance_pct) if run.variance_pct else None,
            potential_annual_difference=float(run.potential_annual_difference) if run.potential_annual_difference else None,
            confidence_score=float(run.confidence_score) if run.confidence_score else None,
            confidence_level=run.confidence_level or "Moderate",
            observations=obs_schemas,
            historical_trend=historical_trend,
            ai_insight=ai_insight,
            created_at=run.created_at.isoformat() if run.created_at else None,
            status=run.status,
            research_notice=(
                "Live market-source search is not configured. Add TAVILY_API_KEY to enable verifiable price research."
                if not obs_schemas and not (settings.TAVILY_API_KEY or settings.BRAVE_SEARCH_API_KEY)
                else None
            ),
        )

    def _generate_historical_trend(
        self,
        contract: ContractPricingDetails,
        benchmark: Dict[str, Any],
        observations: List[MarketPriceObservationSchema],
    ) -> List[Dict[str, Any]]:
        """
        Builds historical price trajectory data points from real observation dates
        and published index trends. Never fabricates imaginary points.
        """
        median = benchmark.get("market_benchmark_median")
        # Only show historical points when they are actually present in recorded
        # market observations. A current median cannot substantiate prior prices.
        dated = {}
        for observation in observations:
            if observation.observation_date and observation.normalized_price:
                dated.setdefault(observation.observation_date[:7], []).append(observation.normalized_price)
        return [
            {
                "period": period,
                "marketPrice": round(float(__import__("statistics").median(prices)), 2),
                "contractPrice": contract.contract_unit_price,
            }
            for period, prices in sorted(dated.items())
        ]


pricing_research_service = PricingResearchService()
