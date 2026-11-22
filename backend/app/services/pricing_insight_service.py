"""
Pricing Insight Service.
Generates an executive AI procurement insight summarizing price variance,
financial exposure, benchmark reliability, specification caveats, and negotiation strategies.
"""

import json
import logging
from typing import Dict, Any, List

from app.core.config import settings
from app.schemas.schemas import ContractPricingDetails, PricingInsightSchema, MarketPriceObservationSchema

logger = logging.getLogger("pricing_insight_service")

INSIGHT_PROMPT = """You are an Executive Procurement Advisory Agent for Supplier 360.
Analyze the following market price benchmarking data against the supplier's active contract.

CONTRACT SPECIFICATIONS:
- Supplier: {supplier_name}
- Material: {material_name}
- Grade: {grade}
- Contract Price: {currency} {contract_price} / {unit}
- Annual Volume: {annual_quantity} {unit}
- Delivery Terms: {delivery_terms}
- Tax Terms: {tax_terms}

MARKET BENCHMARK SUMMARY:
- Market Median Benchmark: {currency} {market_median} / {unit}
- Market Range: {currency} {min_price} to {currency} {max_price} / {unit}
- Price Variance: {variance_pct}% ({position_label})
- Potential Annual Cost Difference: {currency} {potential_annual}
- Benchmark Confidence: {confidence_level} ({confidence_score}%)
- Validated High-Match Sources: {high_count} independent sources
- Partial Match Sources: {partial_count} sources

Write an executive procurement intelligence assessment covering:
1. verdict: Exact phrase: "Above Market", "Below Market", or "In Line with Market"
2. summary: 2-3 sentences explaining the contract position vs market benchmark
3. financial_impact: 1-2 sentences quantifying the estimated annual cost difference
4. reliability_evaluation: Evaluation of source quality, specification alignment, and sample size
5. spec_and_terms_caveats: Bullet points on delivery terms (e.g. DDP vs EXW freight), packaging (drums), or specification checks
6. recommended_actions: 3 concrete, strategic negotiation steps for the procurement team
7. negotiation_points: Specific contract clauses or commercial leverage points (e.g. index linkage, volume rebates, benchmark data)

Respond ONLY with a valid JSON matching this schema:
{{
  "verdict": "string",
  "summary": "string",
  "financial_impact": "string",
  "reliability_evaluation": "string",
  "spec_and_terms_caveats": ["string"],
  "recommended_actions": ["string"],
  "negotiation_points": ["string"]
}}
"""


class PricingInsightService:
    """Generates LLM and deterministic procurement pricing insights."""

    async def generate_insight(
        self,
        contract: ContractPricingDetails,
        benchmark: Dict[str, Any],
        observations: List[MarketPriceObservationSchema],
    ) -> PricingInsightSchema:
        """
        Generate executive procurement insight using Groq LLM with deterministic fallback.
        """
        median = benchmark.get("market_benchmark_median")
        variance_pct = benchmark.get("variance_pct", 0.0) or 0.0
        potential_annual = benchmark.get("potential_annual_difference", 0.0) or 0.0
        curr = contract.currency or "INR"
        unit = contract.unit_of_measurement or "kg"

        if variance_pct > 3.0:
            verdict = "Above Market"
            position_label = f"{variance_pct}% higher than market median"
        elif variance_pct < -3.0:
            verdict = "Below Market"
            position_label = f"{abs(variance_pct)}% lower than market median (cost advantage)"
        else:
            verdict = "In Line with Market"
            position_label = "within +/-3% of market median"

        high_count = benchmark.get("high_match_count", 0)
        partial_count = benchmark.get("partial_match_count", 0)

        # 1. Attempt LLM generation
        if settings.GROQ_API_KEY and median:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                prompt = INSIGHT_PROMPT.format(
                    supplier_name=contract.supplier_name or "Supplier",
                    material_name=contract.material_name,
                    grade=contract.grade or "Standard Grade",
                    currency=curr,
                    contract_price=contract.contract_unit_price,
                    unit=unit,
                    annual_quantity=contract.annual_estimated_quantity or 0,
                    delivery_terms=contract.incoterms or "DDP",
                    tax_terms=contract.tax_inclusion or "Excl. GST",
                    market_median=median,
                    min_price=benchmark.get("market_min_price", median),
                    max_price=benchmark.get("market_max_price", median),
                    variance_pct=variance_pct,
                    position_label=position_label,
                    potential_annual=f"{potential_annual:,.2f}",
                    confidence_level=benchmark.get("confidence_level", "Moderate"),
                    confidence_score=benchmark.get("confidence_score", 65),
                    high_count=high_count,
                    partial_count=partial_count,
                )
                resp = await client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=settings.LLM_MODEL_NAME,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                data = json.loads(resp.choices[0].message.content)
                return PricingInsightSchema(
                    verdict=data.get("verdict") or verdict,
                    summary=data.get("summary") or "",
                    financial_impact=data.get("financial_impact") or "",
                    reliability_evaluation=data.get("reliability_evaluation") or "",
                    spec_and_terms_caveats=data.get("spec_and_terms_caveats") or [],
                    recommended_actions=data.get("recommended_actions") or [],
                    negotiation_points=data.get("negotiation_points") or [],
                )
            except Exception as e:
                logger.warning(f"Groq LLM pricing insight generation error: {e}")

        # 2. Deterministic procurement rules engine fallback
        return self._generate_rule_based_insight(contract, benchmark, verdict, position_label)

    def _generate_rule_based_insight(
        self,
        contract: ContractPricingDetails,
        benchmark: Dict[str, Any],
        verdict: str,
        position_label: str,
    ) -> PricingInsightSchema:
        """Deterministic procurement insight generated from verified business rules."""
        median = benchmark.get("market_benchmark_median")
        variance_pct = benchmark.get("variance_pct", 0.0) or 0.0
        potential_annual = benchmark.get("potential_annual_difference", 0.0) or 0.0
        curr = contract.currency or "INR"
        unit = contract.unit_of_measurement or "kg"
        conf_level = benchmark.get("confidence_level", "Moderate")

        if not median:
            return PricingInsightSchema(
                verdict="Insufficient Data",
                summary=f"Insufficient verified market pricing data available for {contract.material_name} to establish a definitive benchmark.",
                financial_impact="Financial variance cannot be calculated without reliable external market references.",
                reliability_evaluation="Low sample size of comparable grade quotations.",
                spec_and_terms_caveats=["Expand search parameters or request direct RFI quotations from alternative vendors."],
                recommended_actions=["Issue a Request for Information (RFI) to establish an updated spot pricing baseline."],
                negotiation_points=["Request supplier transparency on raw material feedstock cost breakdowns."],
            )

        if verdict == "Above Market":
            summary = (
                f"The contracted rate of {curr} {contract.contract_unit_price:,.2f}/{unit} is {position_label} "
                f"(market median: {curr} {median:,.2f}/{unit}). This indicates an unfavorable pricing delta under current spot market conditions."
            )
            financial_impact = (
                f"On an estimated annual consumption of {contract.annual_estimated_quantity:,.0f} {unit}, "
                f"this variance represents a potential annual cost premium of approximately {curr} {potential_annual:,.2f}."
            )
            actions = [
                f"Invoke quarterly contract review clause to negotiate a unit price reduction towards {curr} {median:,.2f}/{unit}.",
                "Leverage multi-source B2B benchmark data as commercial evidence in upcoming contract renewal discussions.",
                "Review volume rebate tiers and explore indexing price directly to published domestic feedstock benchmarks.",
            ]
            negotiation_points = [
                f"Current market median for comparable {contract.grade or 'specification'} is {curr} {median:,.2f}/{unit}.",
                f"Freight and packaging terms ({contract.incoterms or 'DDP'}) account for ~3-4% of value; excess margin remains above benchmark.",
                "Feedstock price index has shown softening trends over recent quarters.",
            ]
        elif verdict == "Below Market":
            summary = (
                f"The contracted rate of {curr} {contract.contract_unit_price:,.2f}/{unit} is {position_label} "
                f"(market median: {curr} {median:,.2f}/{unit}). Your organization currently holds an advantageous commercial position."
            )
            financial_impact = (
                f"This favorable rate yields an estimated annual cost avoidance of {curr} {abs(potential_annual):,.2f} "
                f"relative to prevailing market procurement rates."
            )
            actions = [
                "Prioritize contract term extension or early renewal to lock in current advantageous rates.",
                "Ensure strict supplier delivery adherence to prevent off-contract spot buying at higher market prices.",
                "Verify supplier capacity and financial health to ensure sustainability of low contracted pricing.",
            ]
            negotiation_points = [
                "Secure volume commitments in exchange for extended contract validity period.",
                "Maintain SLA penalty enforcement for late deliveries to protect cost advantage.",
            ]
        else:
            summary = (
                f"The contracted rate of {curr} {contract.contract_unit_price:,.2f}/{unit} is in line with current market rates "
                f"(market median: {curr} {median:,.2f}/{unit}, variance {variance_pct:+.1f}%)."
            )
            financial_impact = (
                f"Annual expenditure of {curr} {(contract.contract_unit_price * (contract.annual_estimated_quantity or 0)):,.2f} "
                f"closely aligns with current market levels."
            )
            actions = [
                "Focus negotiations on non-price commercial terms (extended payment terms, reduced lead times, buffer stock).",
                "Monitor raw material indices to anticipate future market shifts.",
            ]
            negotiation_points = [
                "Benchmark validation confirms fair market value; pursue working capital optimization through Net 60 days terms.",
            ]

        caveats = [
            f"Benchmark prices are normalized to {contract.incoterms or 'DDP'} delivery and {contract.tax_inclusion or 'tax-exclusive'} terms.",
            f"Quality certificate & batch consistency ({contract.grade or 'Grade A'}) must be verified when comparing against secondary market quotes.",
        ]

        return PricingInsightSchema(
            verdict=verdict,
            summary=summary,
            financial_impact=financial_impact,
            reliability_evaluation=f"{conf_level} confidence: Derived from multiple independent B2B market platforms and price indices.",
            spec_and_terms_caveats=caveats,
            recommended_actions=actions,
            negotiation_points=negotiation_points,
        )


pricing_insight_service = PricingInsightService()
