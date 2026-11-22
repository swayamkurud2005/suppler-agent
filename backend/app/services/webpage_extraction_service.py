"""
Webpage Extraction Service.
Extracts structured raw material pricing records from discovered web sources.
Supports live HTTP scraping with BeautifulSoup + LLM extraction, falling back to
high-precision snippet parsing when sites are protected or inaccessible.
"""

import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.schemas.schemas import ContractPricingDetails
from app.services.numeric_parsing import parse_numeric_price

logger = logging.getLogger("webpage_extraction_service")

PAGE_EXTRACT_PROMPT = """You are a Procurement Market Intelligence Data Extractor.
Extract structured pricing, product grade, and commercial terms from the text of a discovered market source.

TARGET MATERIAL CONTEXT:
Material: {target_material}
Expected Unit: {target_unit}

SOURCE TEXT:
{text_content}

Extract:
1. material_name: Specific material name mentioned
2. grade: Grade, specification, purity, or standard (e.g. Grade A, IS 2062, Technical Grade, or null)
3. specification: Specific technical metrics (viscosity, thickness, purity)
4. price: Numeric price value (e.g. 385.0 or null if not found)
5. currency: Currency code (INR, USD, EUR, etc.)
6. unit: Unit of measurement (kg, tonne, MT, litre, etc.)
7. location: City, state, or country
8. price_type: One of ["supplier offer", "indicative market price", "actual transaction", "wholesale quote"]
9. delivery_conditions: One of ["EXW", "FOB", "CIF", "DDP", "Unspecified"]
10. tax_inclusion: One of ["Excl. Tax", "Incl. Tax", "Net", "Unspecified"]
11. observation_date: Date of observation or publication (YYYY-MM-DD or null)

Respond ONLY with a valid JSON matching this schema:
{{
  "material_name": "string",
  "grade": "string or null",
  "specification": "string or null",
  "price": float or null,
  "currency": "string",
  "unit": "string",
  "location": "string or null",
  "price_type": "string",
  "delivery_conditions": "string",
  "tax_inclusion": "string",
  "observation_date": "string or null"
}}
"""


class WebpageExtractionService:
    """Extracts verified pricing records from discovered search results."""

    @staticmethod
    def _skip(source_hit: Dict[str, Any], stage: str, reason: str) -> None:
        """Record why a candidate was rejected without fabricating a price."""
        source_hit["_pricing_skip_reason"] = f"{stage}: {reason}"
        logger.info("Skipping market source at %s (%s): %s", source_hit.get("url") or "unknown URL", stage, reason)

    async def extract_record_from_source(
        self,
        source_hit: Dict[str, Any],
        contract: ContractPricingDetails,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract a structured market price record from a discovered search hit.
        Attempts HTTP page content retrieval first, falling back to snippet analysis.
        """
        url = source_hit.get("url", "")
        title = source_hit.get("title", "")
        snippet = source_hit.get("snippet", "")
        source_name = source_hit.get("source_name") or "Market Source"

        if not isinstance(url, str) or not re.match(r"^https?://[^\s]+$", url, re.I):
            self._skip(source_hit, "source_validation", "missing or invalid source URL")
            return None

        full_page_text = ""
        # 1. Attempt to fetch page content where technically permitted
        if url.startswith("http"):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                            tag.decompose()
                        clean_text = " ".join(soup.get_text().split())
                        if len(clean_text) > 100:
                            full_page_text = clean_text[:4000]
            except Exception as e:
                logger.debug(f"Direct fetch of {url} skipped/failed ({e}); using snippet parsing.")

        # Combined text: snippet + title + page text (if available)
        combined_text = f"Title: {title}\nSnippet: {snippet}\n{full_page_text}".strip()

        # 2. Extract using Groq LLM if configured
        extracted: Optional[Dict[str, Any]] = None
        if settings.GROQ_API_KEY and len(combined_text) > 40:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                prompt = PAGE_EXTRACT_PROMPT.format(
                    target_material=contract.material_name,
                    target_unit=contract.unit_of_measurement,
                    text_content=combined_text[:3000],
                )
                response = await client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=settings.LLM_MODEL_NAME,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                raw_json = response.choices[0].message.content
                parsed = json.loads(raw_json)
                llm_price = parse_numeric_price(parsed.get("price"))
                if llm_price is not None and llm_price > 0:
                    parsed["price"] = llm_price
                    extracted = parsed
                else:
                    self._skip(source_hit, "llm_price_validation", "missing, invalid, or non-positive price")
            except Exception as e:
                logger.warning("LLM page extraction failed for %s: %s", url, e)

        # 3. Deterministic Regex Fallback if LLM extraction did not yield a valid price
        if not extracted:
            extracted = self._heuristic_extract(combined_text, contract)

        raw_price = parse_numeric_price(extracted.get("price")) if extracted else None
        if raw_price is None or raw_price <= 0:
            self._skip(source_hit, "price_validation", "no verifiable positive price")
            return None

        raw_currency = (extracted.get("currency") or "").upper().strip()
        raw_unit = (extracted.get("unit") or "").lower().strip()
        material_name = (extracted.get("material_name") or contract.material_name or "").strip()
        if not material_name or not raw_currency or not raw_unit:
            self._skip(source_hit, "observation_validation", "missing material name, currency, or unit")
            return None

        # Build clean observation record
        return {
            "source_name": source_name,
            "source_url": url,
            "material_name": material_name,
            "grade": extracted.get("grade") or contract.grade,
            "specification": extracted.get("specification"),
            "raw_price": raw_price,
            "raw_currency": raw_currency,
            "raw_unit": raw_unit,
            "location": extracted.get("location") or "India",
            "observation_date": extracted.get("observation_date") or datetime.now().strftime("%Y-%m-%d"),
            "price_type": extracted.get("price_type") or "supplier offer",
            "delivery_conditions": extracted.get("delivery_conditions") or "Unspecified",
            "tax_inclusion": extracted.get("tax_inclusion") or "Excl. Tax",
            "snippet": snippet or title,
        }

    def _heuristic_extract(self, text: str, contract: ContractPricingDetails) -> Dict[str, Any]:
        """Deterministic regex parsing for prices, currencies, and units."""
        # Find price patterns: "Rs 385/kg", "INR 390 - 410/kg", "₹380 per Kilogram", "$4.50/kg", "53,500/tonne"
        price = None
        currency = None
        unit = None

        # Price regex matching
        price_patterns = [
            r"(?:price|rate|quote|quoted\s+at)\s*[:\-]?\s*(?:is\s*)?(INR|USD|EUR|₹|\$|€|Rs\.?)\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:[-–to]\s*([0-9,]+(?:\.[0-9]+)?))?\s*(?:per|\/)\s*([a-zA-Z]+)",
            r"(INR|USD|EUR|₹|\$|€|Rs\.?)\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:[-–to]\s*([0-9,]+(?:\.[0-9]+)?))?\s*(?:per|\/)\s*([a-zA-Z]+)",
            r"([0-9,]+(?:\.[0-9]+)?)\s*(INR|USD|EUR|₹|\$|€|Rs\.?)\s*(?:per|\/)\s*([a-zA-Z]+)",
        ]

        for pat in price_patterns:
            m = re.search(pat, text, re.I)
            if m:
                groups = m.groups()
                # The third pattern is "price currency per unit"; unlike the
                # first two, its first capture is the numeric price.
                reversed_price_currency = bool(groups and re.fullmatch(r"[0-9,]+(?:\.[0-9]+)?", groups[0] or ""))
                # Parse currency symbol
                curr_sym = (groups[1] if reversed_price_currency else groups[0]) or "INR"
                if any(x in curr_sym for x in ["₹", "Rs", "INR"]): currency = "INR"
                elif "$" in curr_sym or "USD" in curr_sym: currency = "USD"
                elif "€" in curr_sym or "EUR" in curr_sym: currency = "EUR"

                # Parse price (take midpoint if range)
                low_p = parse_numeric_price(groups[0] if reversed_price_currency else groups[1])
                if low_p is None:
                    continue
                if not reversed_price_currency and len(groups) > 2 and groups[2]:
                    high_p = parse_numeric_price(groups[2])
                    if high_p is None:
                        continue
                    price = round((low_p + high_p) / 2.0, 2)
                else:
                    price = low_p

                # Parse unit
                unit_index = 2 if reversed_price_currency else 3
                if len(groups) > unit_index and groups[unit_index]:
                    u = groups[unit_index].lower()
                    if u in ("kilogram", "kgs"): unit = "kg"
                    elif u in ("metric tonne", "metric ton", "ton"): unit = "tonne"
                    else: unit = u
                break

        # Grade extraction
        grade = None
        grade_match = re.search(r"\b(Grade\s+[A-Za-z0-9\-]+|Prime\s+Grade|Standard\s+Grade|General\s+Grade|IS\s*\d+|DGEBA)\b", text, re.I)
        if grade_match:
            grade = grade_match.group(0).strip()

        # Inco / delivery terms
        delivery = "Unspecified"
        if "ex-works" in text.lower() or "ex-factory" in text.lower() or "ex-plant" in text.lower() or "exw" in text.lower():
            delivery = "EXW"
        elif "ddp" in text.lower() or "door delivery" in text.lower():
            delivery = "DDP"
        elif "fob" in text.lower():
            delivery = "FOB"
        elif "cif" in text.lower():
            delivery = "CIF"

        # Price type
        price_type = "supplier offer"
        if "spot" in text.lower() or "index" in text.lower():
            price_type = "indicative market price"
        elif "wholesale" in text.lower() or "bulk" in text.lower():
            price_type = "wholesale quote"
        elif "settlement" in text.lower() or "transaction" in text.lower():
            price_type = "actual transaction"

        return {
            "material_name": contract.material_name,
            "grade": grade,
            "specification": None,
            "price": price,
            "currency": currency,
            "unit": unit,
            "location": "India",
            "price_type": price_type,
            "delivery_conditions": delivery,
            "tax_inclusion": "Excl. Tax",
            "observation_date": datetime.now().strftime("%Y-%m-%d"),
        }


webpage_extraction_service = WebpageExtractionService()
