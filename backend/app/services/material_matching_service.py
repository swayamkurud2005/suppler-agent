"""
Material Matching Service.
Evaluates whether a discovered market pricing record is genuinely comparable to
the contract material specifications.
Assigns match classification:
- high: Identical or functionally equivalent material, grade, and commercial scale.
- partial: Same material family but different grade, packaging, or unverified spec.
- low: Feedstock, distant grade, or consumer retail form.
- not_comparable: Incompatible product, invalid unit, or irreconcilable terms.
"""

import re
import logging
from typing import Dict, Any, Tuple

from app.schemas.schemas import ContractPricingDetails

logger = logging.getLogger("material_matching_service")


class MaterialMatchingService:
    """Classifies market records based on material similarity, grade compatibility, and scale."""

    def evaluate_match(
        self,
        observation: Dict[str, Any],
        contract: ContractPricingDetails,
    ) -> Tuple[str, str, bool]:
        """
        Evaluate match classification and rationale.
        Returns: (match_classification, match_rationale, is_included_in_benchmark)
        """
        contract_mat = contract.material_name.lower().strip()
        contract_grade = (contract.grade or "").lower().strip()
        
        obs_mat = (observation.get("material_name") or "").lower().strip()
        obs_grade = (observation.get("grade") or "").lower().strip()
        snippet = (observation.get("snippet") or "").lower().strip()
        title = (observation.get("source_name") or "").lower().strip()

        # Extract core material keywords (e.g. "epoxy resin", "steel", "copper", "aluminium", "cement")
        core_keywords = self._extract_core_keywords(contract_mat)
        
        # Check if the observation text contains the core material
        text_corpus = f"{obs_mat} {obs_grade} {snippet} {title}".lower()
        has_core_match = any(kw in text_corpus for kw in core_keywords)

        if not has_core_match:
            return (
                "not_comparable",
                f"Material does not match contract commodity '{contract.material_name}'.",
                False,
            )

        # Check for retail consumer packaging or hobbyist glue
        # (e.g. 50g tubes, syringes, retail adhesives vs 200kg industrial drums)
        retail_indicators = ["50g", "100g", "250g", "syringe", "tube", "diy kit", "art resin", "craft"]
        if any(r in text_corpus for r in retail_indicators):
            return (
                "low",
                "Consumer/retail craft formulation; not comparable to industrial wholesale contract scale.",
                False,
            )

        # Check for raw feedstock vs formulated material (e.g. Bisphenol-A / ECH raw chemicals vs finished Epoxy Resin)
        if any(f in contract_mat for f in ["resin", "epoxy"]) and not any(k in obs_mat for k in ["resin", "epoxy", "dgeba"]):
            if any(f in text_corpus for f in ["bisphenol", "epichlorohydrin", "phenol"]):
                return (
                    "low",
                    "Feedstock chemical precursor rather than formulated resin compound.",
                    False,
                )

        # Grade Evaluation
        grade_match_level = "exact"
        if contract_grade:
            if contract_grade in obs_grade or contract_grade in text_corpus:
                grade_match_level = "exact"
            elif any(g in text_corpus for g in ["prime grade", "grade a", "standard grade", "dgeba 128"]):
                grade_match_level = "equivalent"
            elif any(g in text_corpus for g in ["grade b", "technical grade", "off-grade", "recycled"]):
                grade_match_level = "inferior"
            else:
                grade_match_level = "unspecified"
        else:
            grade_match_level = "unspecified"

        # Packaging / Commercial scale
        is_bulk_scale = any(w in text_corpus for w in ["drum", "bulk", "tonne", "ton", "mt", "tanker", "200kg", "wholesale"])

        # Determine Classification
        if grade_match_level in ("exact", "equivalent"):
            rationale = f"High match: Compatible {contract.material_name} specification"
            if grade_match_level == "exact" and contract_grade:
                rationale += f" with verified {contract.grade}."
            elif contract_grade:
                rationale += f" (functionally equivalent to {contract.grade})."
            else:
                rationale += " for industrial procurement."
            return ("high", rationale, True)

        elif grade_match_level == "unspecified":
            if is_bulk_scale:
                return (
                    "partial",
                    f"Partial match: Same material family in commercial scale, but specific {contract.grade or 'grade'} standard was not explicitly verified.",
                    False,
                )
            else:
                return (
                    "partial",
                    "Partial match: General industrial material; grade or testing cert not fully specified.",
                    False,
                )

        elif grade_match_level == "inferior":
            return (
                "low",
                f"Low match: Identified as secondary/inferior grade (e.g. Grade B); differs from contracted {contract.grade or 'Grade A'}.",
                False,
            )

        return (
            "partial",
            "Partial match: Discovered pricing belongs to same commodity class with minor specification variances.",
            False,
        )

    def _extract_core_keywords(self, mat_name: str) -> list[str]:
        """Extract dominant commodity search tokens."""
        clean = re.sub(r"^[A-Z0-9\-]+\s+", "", mat_name).strip()
        tokens = [clean]
        words = clean.split()
        if len(words) >= 2:
            tokens.append(f"{words[0]} {words[1]}")
        for w in words:
            if len(w) > 3 and w not in ("industrial", "commercial", "specialty", "grade", "pure"):
                tokens.append(w)
        return list(set(tokens))


material_matching_service = MaterialMatchingService()
