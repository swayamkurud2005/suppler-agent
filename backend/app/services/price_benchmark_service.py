"""
Price Benchmark Service.
Computes median market benchmark, minimum, maximum, variance percentage,
and potential annual difference based on validated high-match market observations.
"""

import statistics
import logging
from typing import List, Dict, Any, Optional

from app.schemas.schemas import ContractPricingDetails, MarketPriceObservationSchema

logger = logging.getLogger("price_benchmark_service")


class PriceBenchmarkService:
    """Calculates market benchmarks and variance against contract baseline."""

    def compute_benchmark(
        self,
        contract: ContractPricingDetails,
        observations: List[MarketPriceObservationSchema],
    ) -> Dict[str, Any]:
        """
        Calculate statistical benchmark metrics from validated observations.
        Only 'high' match records are used in the primary benchmark.
        """
        # Filter high-match records
        high_matches = [
            o for o in observations
            if o.match_classification == "high" and o.is_included_in_benchmark and o.normalized_price > 0
        ]

        # Partial matches are contextual only; they must never establish a benchmark.
        partial_matches = [
            o for o in observations
            if o.match_classification == "partial" and o.normalized_price > 0
        ]

        contract_price = float(contract.contract_unit_price)
        annual_qty = float(contract.annual_estimated_quantity or contract.contract_quantity or 0.0)

        # Do not present a market comparison unless at least two independently
        # sourced high-match observations support it.
        if len(high_matches) < 2:
            return {
                "market_benchmark_median": None,
                "market_min_price": None,
                "market_max_price": None,
                "market_avg_price": None,
                "variance_pct": None,
                "potential_annual_difference": None,
                "confidence_score": 10.0,
                "confidence_level": "Insufficient market data",
                "high_match_count": len(high_matches),
                "partial_match_count": len(partial_matches),
                "is_sufficient": False,
            }

        # Valid high-match benchmark calculation
        prices = [o.normalized_price for o in high_matches]
        median_price = round(float(statistics.median(prices)), 2)
        min_p = round(float(min(prices)), 2)
        max_p = round(float(max(prices)), 2)
        avg_p = round(float(statistics.mean(prices)), 2)

        price_diff = round(contract_price - median_price, 2)
        variance_pct = round(((contract_price - median_price) / median_price) * 100, 2)
        potential_annual = round(price_diff * annual_qty, 2) if annual_qty > 0 else 0.0

        # Evaluate confidence score (0 to 100)
        # Factors: source count, domain diversity, price variance
        unique_domains = len(set(o.source_name for o in high_matches))
        price_spread_pct = ((max_p - min_p) / avg_p) if avg_p > 0 else 1.0

        score = 50.0
        score += min(len(high_matches) * 10.0, 30.0) # Up to +30 for sample size
        score += min(unique_domains * 5.0, 15.0)     # Up to +15 for domain diversity
        if price_spread_pct < 0.15:
            score += 10.0                             # +10 for tight clustering (<15% spread)
        elif price_spread_pct > 0.40:
            score -= 15.0                             # -15 for high dispersion (>40% spread)

        confidence_score = round(max(min(score, 98.0), 20.0), 1)

        if confidence_score >= 75.0:
            confidence_level = "High"
        elif confidence_score >= 50.0:
            confidence_level = "Moderate"
        else:
            confidence_level = "Low"

        return {
            "market_benchmark_median": median_price,
            "market_min_price": min_p,
            "market_max_price": max_p,
            "market_avg_price": avg_p,
            "variance_pct": variance_pct,
            "potential_annual_difference": potential_annual,
            "confidence_score": confidence_score,
            "confidence_level": confidence_level,
            "high_match_count": len(high_matches),
            "partial_match_count": len(partial_matches),
            "is_sufficient": True,
        }


price_benchmark_service = PriceBenchmarkService()
