"""Strict, reusable parsing for externally supplied monetary values."""

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


_CURRENCY_MARKERS = re.compile(r"(?:INR|USD|EUR|GBP|RS\.?|₹|\$|€|£)", re.IGNORECASE)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")


def parse_numeric_price(value: Any, *, field_name: str = "price") -> Optional[float]:
    """Parse a single numeric price, returning ``None`` when it is absent.

    The function deliberately rejects textual ranges (for example ``10-12``),
    units, and malformed values. A caller must decide how to interpret those
    formats instead of accidentally comparing an invented value. Zero is kept
    as a legitimate numeric result; market-observation validation decides
    whether it is a usable price.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = _CURRENCY_MARKERS.sub("", cleaned).replace(",", "").strip()
    if not _NUMBER.fullmatch(cleaned):
        return None
    try:
        result = float(Decimal(cleaned))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None
