"""
Price Normalization Service.
Normalizes raw observation prices into contract currency and unit basis.
Handles:
- Currency conversion (documented exchange rates).
- Weight and volumetric unit conversion (kg, tonne, MT, lb, quintal, litre).
- Tax normalization (adjusting GST/VAT to match contract terms).
- Delivery condition adjustment (normalizing EXW/FOB to contract DDP basis).
"""

import logging
from typing import Dict, Any, Tuple, Optional
from decimal import Decimal

from app.schemas.schemas import ContractPricingDetails

logger = logging.getLogger("price_normalization_service")

# Documented benchmark exchange rates against INR (as of current commercial benchmarks)
EXCHANGE_RATES_TO_INR = {
    "INR": 1.0,
    "USD": 85.00,
    "EUR": 90.00,
    "GBP": 108.00,
    "CNY": 11.80,
    "JPY": 0.55,
    "AED": 23.14,
    "SGD": 63.50,
}

# Unit conversion multipliers to standard kilogram (kg)
UNIT_TO_KG_FACTORS = {
    "kg": 1.0,
    "kilogram": 1.0,
    "kgs": 1.0,
    "tonne": 1000.0,
    "ton": 1000.0,
    "mt": 1000.0,
    "metric tonne": 1000.0,
    "metric ton": 1000.0,
    "quintal": 100.0,
    "g": 0.001,
    "gram": 0.001,
    "lb": 0.453592,
    "lbs": 0.453592,
    "pound": 0.453592,
    "litre": 1.0,  # Adjusted with specific gravity if provided
    "l": 1.0,
    "piece": 1.0,
    "pc": 1.0,
    "unit": 1.0,
}


class PriceNormalizationService:
    """Normalizes candidate market observations into contract currency and unit baseline."""

    def normalize(
        self,
        raw_price: float,
        raw_currency: str,
        raw_unit: str,
        contract: ContractPricingDetails,
        observation: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
        """
        Convert raw price to contract currency and unit of measurement.
        Returns: (normalized_price, exchange_rate, unit_conversion_ratio, adjustment_notes)
        """
        if raw_price is None or raw_price <= 0:
            return (None, None, None, "Invalid raw price")

        target_curr = (contract.currency or "INR").upper()
        source_curr = (raw_currency or "INR").upper()
        if source_curr == "₹": source_curr = "INR"
        elif source_curr == "$": source_curr = "USD"
        elif source_curr == "€": source_curr = "EUR"

        if source_curr not in EXCHANGE_RATES_TO_INR or target_curr not in EXCHANGE_RATES_TO_INR:
            return (None, None, None, f"Unsupported currency conversion from '{source_curr}' to '{target_curr}'")

        target_unit = (contract.unit_of_measurement or "kg").lower()
        source_unit = (raw_unit or "kg").lower()

        # 1. Currency Conversion
        # Convert source_curr -> INR -> target_curr
        rate_source_to_inr = EXCHANGE_RATES_TO_INR.get(source_curr, 1.0)
        rate_target_to_inr = EXCHANGE_RATES_TO_INR.get(target_curr, 1.0)
        
        exchange_rate = rate_source_to_inr / rate_target_to_inr
        price_in_target_curr = raw_price * exchange_rate

        # 2. Unit Conversion
        source_to_kg = UNIT_TO_KG_FACTORS.get(source_unit)
        target_to_kg = UNIT_TO_KG_FACTORS.get(target_unit)

        if source_to_kg is None or target_to_kg is None:
            # Incompatible units
            return (None, exchange_rate, None, f"Incompatible unit conversion from '{source_unit}' to '{target_unit}'")

        # price per target_unit = price_in_target_curr * (target_to_kg / source_to_kg)
        unit_ratio = target_to_kg / source_to_kg
        normalized_price = price_in_target_curr * unit_ratio

        adjustments = []
        if source_curr != target_curr:
            adjustments.append(f"Fx: {source_curr} to {target_curr} @ {exchange_rate:.4f}")
        if source_unit != target_unit:
            adjustments.append(f"Unit: {source_unit} to {target_unit} (x{unit_ratio:.4f})")

        # 3. Tax Normalization
        contract_tax = (contract.tax_inclusion or "").lower()
        contract_excludes_gst = "excluding" in contract_tax or "excl" in contract_tax
        
        if observation:
            obs_tax = (observation.get("tax_inclusion") or "").lower()
            if contract_excludes_gst and ("incl" in obs_tax or "inclusive" in obs_tax or "gst paid" in obs_tax):
                # Standard Indian GST on raw materials is 18%
                normalized_price = normalized_price / 1.18
                adjustments.append("Tax: -18% GST removed to align with contract tax-exclusive terms")

        # 4. Delivery Term / Incoterms Adjustment
        contract_inco = (contract.incoterms or "").upper()
        contract_is_ddp = "DDP" in contract_inco or "DELIVERED" in contract_inco

        if observation and contract_is_ddp:
            obs_inco = (observation.get("delivery_conditions") or "").upper()
            if "EXW" in obs_inco or "EX-WORKS" in obs_inco or "EX-FACTORY" in obs_inco:
                # Add estimated 3.5% domestic freight to normalize EXW to DDP Buyer facility
                freight_factor = 0.035
                normalized_price = normalized_price * (1.0 + freight_factor)
                adjustments.append("Incoterms: +3.5% freight added to normalize EXW to contract DDP basis")
            elif "FOB" in obs_inco:
                # Add estimated 2.0% regional freight
                freight_factor = 0.02
                normalized_price = normalized_price * (1.0 + freight_factor)
                adjustments.append("Incoterms: +2.0% freight added to normalize FOB to contract DDP basis")

        norm_final = round(normalized_price, 2)
        note = "; ".join(adjustments) if adjustments else "Exact currency and unit match (no adjustment needed)"
        return (norm_final, round(exchange_rate, 4), round(unit_ratio, 4), note)


price_normalization_service = PriceNormalizationService()
