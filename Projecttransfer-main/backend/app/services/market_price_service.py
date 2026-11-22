"""Validated commodity and supplier benchmark ingestion."""

import asyncio
import csv
import io
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import MarketPriceBenchmark, Product

METALCHARTS_URL = "https://api.metalcharts.org/v1/prices/"
METALS = {"HG": "Copper", "ALI": "Aluminium", "NI": "Nickel","ZN": "Zinc","JBP": "Steel"}
API_KEY_MISSING = "MetalCharts API key is not configured. Please add your API key to the backend .env file."


def configured_api_key() -> str | None:
    key = settings.METALCHARTS_API_KEY.strip()
    if not key or key.casefold() == "put api key here" or " " in key:
        return None
    return key

"""
def _request_prices(api_key: str) -> dict:
    request = Request(
        f"{METALCHARTS_URL}?symbols=XCU,ALI&currency=INR&unit=kg",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"MetalCharts returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to retrieve prices from MetalCharts.") from exc
"""
"""
#THIS IS NEW ONE ADDED BY Aishwarya
def _request_prices(api_key: str) -> dict:
    symbols = ",".join(METALS.keys())

    request = Request(
        f"{METALCHARTS_URL}?symbols={symbols}&currency=INR&unit=kg",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        raise ValueError(
            f"MetalCharts returned HTTP {exc.code}."
        ) from exc

    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Unable to retrieve prices from MetalCharts."
        ) from exc
"""
# New one again:

def _request_prices(api_key: str) -> dict:
    symbols = ",".join(METALS.keys())

    url = f"{METALCHARTS_URL}?symbols={symbols}&currency=INR&unit=kg"

    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "Supplier360/1.0",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        raise ValueError(
            f"MetalCharts returned HTTP {exc.code}."
        ) from exc

    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Unable to retrieve prices from MetalCharts."
        ) from exc


def normalize_material_price(price, currency: str, unit: str) -> Decimal:
    """Accept only quotes already normalized by MetalCharts to INR per kg."""
    if currency.upper() != "INR" or unit.lower() != "kg":
        raise ValueError("Metal price must be quoted in INR per kg.")
    try:
        value = Decimal(str(price))
    except InvalidOperation as exc:
        raise ValueError("Metal price is not numeric.") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("Metal price must be a positive finite value.")
    return value.quantize(Decimal("0.0001"))


async def save_market_benchmark(db: AsyncSession, *, product: Product, price: Decimal,
                               currency: str, unit: str, source_name: str, source_url: str,
                               benchmark_type: str, benchmark_date: date | None = None,
                               product_specification: str | None = None,
                               metal_symbol: str | None = None,
                               verification_status: str = "verified") -> MarketPriceBenchmark:
    benchmark = MarketPriceBenchmark(
        product_id=product.product_id, benchmark_price=price, currency=currency.upper(),
        unit=unit, region="Global commodity reference" if benchmark_type == "commodity_reference" else None,
        product_specification=product_specification, benchmark_date=benchmark_date or date.today(),
        source_name=source_name, source_url=source_url, benchmark_type=benchmark_type,
        retrieved_at=datetime.now(timezone.utc), verification_status=verification_status,
        match_confidence=Decimal("100.00") if verification_status == "verified" else None,
        metal_symbol=metal_symbol,
    )
    db.add(benchmark)
    await db.flush()
    return benchmark


async def fetch_raw_material_prices() -> list[dict]:
    key = configured_api_key()
    if not key:
        raise ValueError(API_KEY_MISSING)
    payload = await asyncio.to_thread(_request_prices, key)
    if payload.get("success") is not True or not isinstance(payload.get("data"), dict):
        raise ValueError("MetalCharts returned an invalid price response.")
    output = []
    for symbol, name in METALS.items():
        quote = payload["data"].get(symbol)
        if not isinstance(quote, dict) or "price" not in quote:
            raise ValueError(f"MetalCharts response did not include {name} ({symbol}).")
        currency, unit = quote.get("currency"), quote.get("unit")
        if not currency or not unit:
            raise ValueError(f"MetalCharts quote for {name} is missing currency or unit metadata.")
        price = normalize_material_price(quote["price"], currency, unit)
        output.append({"symbol": symbol, "name": name, "price": price,
                       "currency": currency, "unit": unit,
                       "timestamp": quote.get("timestamp") or payload.get("timestamp")})
    return output

async def refresh_raw_material_benchmarks(db: AsyncSession) -> list[MarketPriceBenchmark]:
    if not configured_api_key():
        raise ValueError(API_KEY_MISSING)
    today_utc = datetime.now(timezone.utc).date()
    cached_result = await db.execute(
        select(MarketPriceBenchmark)
        .where(
            MarketPriceBenchmark.benchmark_type == "commodity_reference",
            MarketPriceBenchmark.source_name == "MetalCharts",
            MarketPriceBenchmark.benchmark_date == today_utc,
            MarketPriceBenchmark.metal_symbol.in_(list(METALS)),
        )
    )
    cached = cached_result.scalars().all()
    if {benchmark.metal_symbol for benchmark in cached} == set(METALS):
        return cached
    quotes = await fetch_raw_material_prices()
    saved = []
    for quote in quotes:
        result = await db.execute(select(Product).where(Product.product_name.ilike(quote["name"])))
        product = result.scalars().first()
        if product is None:
            product = Product(product_name=quote["name"], category="Raw Material",
                              description=f"{quote['name']} commodity reference price",
                              package_unit="kg", currency="INR")
            db.add(product)
            await db.flush()
        saved.append(await save_market_benchmark(
            db, product=product, price=quote["price"], currency="INR", unit="kg",
            source_name="MetalCharts", source_url="https://metalcharts.org",
            benchmark_type="commodity_reference", metal_symbol=quote["symbol"],
            benchmark_date=today_utc,
            product_specification=f"Indicative {quote['name']} commodity reference; not a supplier quotation",
        ))
    return saved



async def import_supplier_quotation(db: AsyncSession, rows: list[dict]) -> list[MarketPriceBenchmark]:
    saved = []
    for row in rows:
        name = str(row.get("product_name", "")).strip()
        unit = str(row.get("unit", "")).strip()
        currency = str(row.get("currency", "")).strip().upper()
        specification = str(row.get("product_specification", "")).strip()
        if not name or not unit or not currency or not specification:
            raise ValueError("Each quotation must include product_name, product_specification, currency and unit.")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Currency must be an ISO-style three-letter code such as INR or USD.")
        if len(unit) > 50 or not re.fullmatch(r"[A-Za-z0-9._ -]+", unit):
            raise ValueError("Unit must be a valid label of 50 characters or fewer.")
        try:
            price = Decimal(str(row.get("price", "")))
        except InvalidOperation as exc:
            raise ValueError("Quotation price must be numeric.") from exc
        if not price.is_finite() or price <= 0:
            raise ValueError("Quotation price must be a positive finite value.")
        result = await db.execute(select(Product).where(Product.product_name.ilike(name)))
        product = result.scalars().first()
        if product is None:
            product = Product(product_name=name, category=row.get("category"),
                              description=specification, package_unit=unit, currency=currency)
            db.add(product)
            await db.flush()
        elif product.description and product.description.strip().casefold() != specification.casefold():
            raise ValueError(f"Specification does not match existing product '{name}'.")
        elif product.package_unit and product.package_unit.strip().casefold() != unit.casefold():
            raise ValueError(f"Unit does not match existing product '{name}'.")
        if not product.description:
            product.description = specification
        if not product.package_unit:
            product.package_unit = unit
        if not product.currency:
            product.currency = currency
        if not product.category and row.get("category"):
            product.category = str(row["category"]).strip()
        saved.append(await save_market_benchmark(
            db, product=product, price=price, currency=currency, unit=unit,
            source_name=str(row.get("source_name") or "Supplier quotation"),
            source_url=str(row.get("source_url") or ""), benchmark_type="supplier_quotation",
            product_specification=specification,
            verification_status="verified" if row.get("verified") is True else "unverified",
        ))
    return saved


def parse_catalogue_csv(contents: bytes) -> list[dict]:
    try:
        text = contents.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Catalogue must be a UTF-8 CSV file.") from exc
    required = {"product_name", "product_specification", "price", "currency", "unit"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV columns must include: product_name, product_specification, price, currency, unit.")
    return list(reader)


async def import_supplier_catalogue(db: AsyncSession, contents: bytes, filename: str) -> list[MarketPriceBenchmark]:
    """Import a validated CSV/XLSX/XLS catalogue as unverified benchmark records."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "csv":
        rows = parse_catalogue_csv(contents)
    elif suffix in {"xlsx", "xls"}:
        import pandas as pd
        frame = pd.read_excel(io.BytesIO(contents))
        rows = frame.fillna("").to_dict(orient="records")
        required = {"product_name", "product_specification", "price", "currency", "unit"}
        if not rows or not required.issubset(set(rows[0])):
            raise ValueError("Catalogue columns must include: product_name, product_specification, price, currency, unit.")
    else:
        raise ValueError("Upload a CSV or Excel catalogue.")
    for row in rows:
        row["verified"] = False
        row.setdefault("source_name", "Supplier catalogue")
    return await import_supplier_quotation(db, rows)
