import asyncio
from decimal import Decimal

import pytest

from app.core.config import settings
from app.api.v1.endpoints.market_prices import refresh_prices
from app.services import market_price_service as service


def test_placeholder_key_is_unconfigured():
    previous = settings.METALCHARTS_API_KEY
    settings.METALCHARTS_API_KEY = "PUT API KEY HERE"
    try:
        assert service.configured_api_key() is None
    finally:
        settings.METALCHARTS_API_KEY = previous


def test_missing_key_stops_before_network(monkeypatch):
    previous = settings.METALCHARTS_API_KEY
    settings.METALCHARTS_API_KEY = "PUT API KEY HERE"
    monkeypatch.setattr(service, "urlopen", lambda *args, **kwargs: pytest.fail("network must not be called"))
    try:
        with pytest.raises(ValueError, match="MetalCharts API key is not configured"):
            asyncio.run(service.fetch_raw_material_prices())
    finally:
        settings.METALCHARTS_API_KEY = previous


def test_refresh_returns_clear_message_without_key():
    previous = settings.METALCHARTS_API_KEY
    settings.METALCHARTS_API_KEY = "PUT API KEY HERE"
    try:
        response = asyncio.run(refresh_prices(db=None))
        assert response.status == "not_configured"
        assert response.message == service.API_KEY_MISSING
    finally:
        settings.METALCHARTS_API_KEY = previous


def test_normalize_requires_inr_per_kg():
    assert service.normalize_material_price("812.34567", "INR", "kg") == Decimal("812.3457")
    with pytest.raises(ValueError, match="INR per kg"):
        service.normalize_material_price("10", "USD", "kg")


def test_catalogue_csv_requires_compatibility_fields():
    rows = service.parse_catalogue_csv(
        b"product_name,product_specification,price,currency,unit\nBearing,6205-2RS,25,INR,each\n"
    )
    assert rows[0]["product_specification"] == "6205-2RS"
    with pytest.raises(ValueError, match="CSV columns must include"):
        service.parse_catalogue_csv(b"product_name,price\nBearing,25\n")
