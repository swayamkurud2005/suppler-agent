"""
Contract Pricing Extractor Service.
Extracts raw material and commercial details from supplier contracts
using hybrid RAG retrieval and structured LLM extraction with deterministic fallback.

Supports ANY material or product category (metals, chemicals, polymers, minerals,
packaging, agricultural commodities, electronics, etc.).
"""

import re
import json
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.models import (
    Contract,
    ContractProduct,
    PriceResearchRun,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.schemas.schemas import ContractPricingDetails
from app.services.document_parser import parse_document
from app.services.hybrid_retriever import hybrid_retriever
from app.services.numeric_parsing import parse_numeric_price

logger = logging.getLogger("contract_pricing_extractor")

SYSTEM_EXTRACTION_PROMPT = """You are an expert Procurement Contract Analyst specializing in commercial raw material agreements.
Your task is to extract exact commercial and technical raw material details from the provided contract text.

RULES:
1. Extract the actual material/product being purchased, its contracted price, quantity, units, incoterms, and specifications.
2. NEVER invent or hallucinate missing values. If a field is not specified in the text, use null.
3. This can be ANY material: steel, copper, aluminium, cement, plastics, epoxy resin, paper, agricultural commodities, chemicals, etc.
4. Extract the exact contracted currency (e.g. INR, USD, EUR) and unit of measurement (kg, tonne, MT, litre, piece, meter).
5. Extract tax terms (e.g., "Excluded from contract unit price", "Inclusive of GST 18%").
6. Extract delivery terms / Incoterms (e.g., "DDP Chakan", "FOB Mumbai", "EXW").

Respond ONLY with a valid JSON matching this schema:
{
  "material_name": "string (e.g. NS-480 Industrial Epoxy Resin)",
  "grade": "string or null (e.g. Grade A)",
  "product_code": "string or null (e.g. NS480-A)",
  "technical_characteristics": "string or null (summary of key specs, viscosity, purity, etc.)",
  "contract_unit_price": float (e.g. 420.0),
  "currency": "string (e.g. INR, USD, EUR)",
  "unit_of_measurement": "string (e.g. kg, tonne, MT, litre, piece)",
  "contract_quantity": float or null,
  "annual_estimated_quantity": float or null (e.g. 24000.0),
  "contract_effective_date": "string or null (YYYY-MM-DD)",
  "contract_expiry_date": "string or null (YYYY-MM-DD)",
  "delivery_location": "string or null",
  "incoterms": "string or null (e.g. DDP, FOB, CIF, EXW)",
  "tax_inclusion": "string or null (e.g. Excluded from contract unit price, GST extra)",
  "packaging_details": "string or null (e.g. 200 kg sealed steel drums)",
  "supplier_name": "string or null"
}
"""


def _heuristic_extract_pricing(full_text: str, supplier_name: str = "") -> Dict[str, Any]:
    """
    High-precision deterministic parser for structured schedules, tables,
    and clauses across supply agreements.
    """
    res: Dict[str, Any] = {
        "material_name": "Industrial Raw Material",
        "grade": None,
        "product_code": None,
        "technical_characteristics": None,
        "contract_unit_price": 0.0,
        "currency": "INR",
        "unit_of_measurement": "kg",
        "contract_quantity": None,
        "annual_estimated_quantity": None,
        "contract_effective_date": None,
        "contract_expiry_date": None,
        "delivery_location": None,
        "incoterms": None,
        "tax_inclusion": None,
        "packaging_details": None,
        "supplier_name": supplier_name,
        "evidence_sources": [],
    }

    # 1. Product Name & Grade
    # Schedule A / Schedule B or Section 3 patterns
    prod_match = re.search(
        r"(?:Product\s*(?:name)?|Material\s*(?:name)?|The\s+Product\s+is)\s*[:\-]?\s*([A-Za-z0-9\-_\s,\(\)]{3,80}?)(?:\n|\r|,|\.|\s*used\s+in|\s*Internal)",
        full_text,
        re.I,
    )
    if prod_match:
        raw_name = prod_match.group(1).strip()
        # Separate grade if embedded like "NS-480 Industrial Epoxy Resin, Grade A"
        if re.search(r",\s*(?:grade\s*[A-Z0-9]+)", raw_name, re.I):
            parts = raw_name.split(",", 1)
            res["material_name"] = parts[0].strip()
            res["grade"] = parts[1].strip()
        else:
            res["material_name"] = raw_name

    # Grade search if not yet found
    if not res["grade"]:
        grade_match = re.search(r"\b(Grade\s+[A-Za-z0-9\-]+|IS\s*\d+|ASTM\s*[A-Za-z0-9\-]+)\b", full_text, re.I)
        if grade_match:
            res["grade"] = grade_match.group(0).strip()

    # Product code
    code_match = re.search(r"(?:product\s*code|item\s*code|sku|part\s*number)\s*[:\-]?\s*([A-Za-z0-9\-_\/]+)", full_text, re.I)
    if code_match:
        res["product_code"] = code_match.group(1).strip()

    # 2. Price and Currency
    # Look for "Unit price: INR 420/kg" or "base unit price is INR 420 per kilogram" or "₹420/kg"
    price_patterns = [
        r"(?:Unit\s*price|base\s*unit\s*price|Contract\s*Price)\s*[:\-]?\s*(?:is\s*)?(INR|USD|EUR|GBP|₹|\$|€)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:per|\/)\s*([a-zA-Z]+)",
        r"(INR|USD|EUR|GBP|₹|\$|€)\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:per|\/)\s*(kg|kilogram|tonne|MT|ton|litre|piece|unit|meter)",
    ]
    # PDF table extraction often uses "Rate" or "Agreed Price", and the
    # previous patterns also missed the real Unicode rupee / euro symbols.
    price_patterns.extend([
        r"(?:unit\s*(?:price|rate)|base\s*unit\s*price|contract(?:ed)?\s*price|agreed\s*(?:unit\s*)?(?:price|rate)|rate)\s*[:=\-]?\s*(?:is\s*)?(INR|USD|EUR|GBP|₹|\$|€)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:per|\/|each)\s*(kg|kgs?|kilograms?|tonnes?|mt|litres?|ltrs?|pieces?|units?|meters?|metres?|bags?)\b",
        r"(INR|USD|EUR|GBP|₹|\$|€)\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:per|\/|each)\s*(kg|kgs?|kilograms?|tonnes?|mt|litres?|ltrs?|pieces?|units?|meters?|metres?|bags?)\b",
        r"(?:unit\s*(?:price|rate)|base\s*unit\s*price|contract(?:ed)?\s*price|agreed\s*(?:unit\s*)?(?:price|rate)|rate)\s*[:=\-]?\s*(?:is\s*)?(INR|USD|EUR|GBP|₹|\$|€)?\s*([0-9,]+(?:\.[0-9]+)?)(?:\s*\/-)?(?:\s*(?:per|\/|each)\s*(kg|kgs?|kilograms?|tonnes?|mt|litres?|ltrs?|pieces?|units?|meters?|metres?|bags?))?",
        # Some PDF table extractors emit an unknown glyph before the amount
        # (for example "■6,450 per metric tonne").  The price still needs a
        # digit; a comma-only table cell is never a valid amount.
        r"(?:unit\s*(?:price|rate)|base\s*unit\s*price|contract(?:ed)?\s*price|agreed\s*(?:unit\s*)?(?:price|rate)|rate)\s*[:=\-]?\s*(?:is\s*)?(INR|USD|EUR|GBP|₹|\$|€)?\s*(?:[^\w\s]{1,3}\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|\/|each)\s*(metric\s+tonne|metric\s+ton|kg|kgs?|kilograms?|tonnes?|mt|litres?|ltrs?|pieces?|units?|meters?|metres?|bags?)\b",
    ])
    for pat in price_patterns:
        pm = re.search(pat, full_text, re.I)
        if pm:
            curr = pm.group(1) or "INR"
            if curr == "₹": curr = "INR"
            elif curr == "€": curr = "EUR"
            if curr == "₹": curr = "INR"
            elif curr == "$": curr = "USD"
            elif curr == "€": curr = "EUR"
            unit_price = parse_numeric_price(pm.group(2))
            if unit_price is None:
                logger.warning("Ignoring invalid contract price token %r", pm.group(2))
                continue
            res["contract_unit_price"] = unit_price
            res["currency"] = curr.upper()
            unit = (pm.group(3) or "unit").lower()
            unit = {
                "kilograms": "kg", "tonnes": "tonne", "mt": "tonne",
                "litres": "litre", "ltrs": "litre", "pieces": "piece",
                "units": "unit", "metres": "meter",
            }.get(unit, unit)
            if unit in ("kilogram", "kgs"): unit = "kg"
            elif unit in ("metric tonne", "metric ton", "ton"): unit = "tonne"
            res["unit_of_measurement"] = unit
            break

    # 3. Annual and contract quantity
    qty_match = re.search(
        r"(?:annual\s*(?:estimated\s*)?quantity|estimated\s*annual\s*quantity)\s*[:\-]?\s*(?:is\s*)?([0-9,]+)\s*([a-zA-Z]+)?",
        full_text,
        re.I,
    )
    if qty_match:
        val = float(qty_match.group(1).replace(",", ""))
        res["annual_estimated_quantity"] = val
        res["contract_quantity"] = val

    # 4. Delivery location and Incoterms
    inco_match = re.search(r"\b(DDP|FOB|CIF|EXW|CFR|CIP|FCA|CPT|DAP)\s+([^\n\r,\.;]{3,60})", full_text, re.I)
    if inco_match:
        res["incoterms"] = inco_match.group(0).strip()
    else:
        term_match = re.search(r"(?:Delivery\s*term)\s*[:\-]?\s*([^\n\r;]{3,80})", full_text, re.I)
        if term_match:
            res["incoterms"] = term_match.group(1).strip()

    loc_match = re.search(r"(?:Delivery\s*location)\s*[:\-]?\s*([^\n\r;]{5,150})", full_text, re.I)
    if loc_match:
        res["delivery_location"] = loc_match.group(1).strip()

    # 5. Tax Terms (GST / VAT)
    tax_match = re.search(r"(excluding\s+applicable\s+GST|excluding\s+GST|exclusive\s+of\s+tax|including\s+GST|inclusive\s+of\s+GST)", full_text, re.I)
    if tax_match:
        res["tax_inclusion"] = tax_match.group(0).strip()

    # 6. Packaging Details
    pkg_match = re.search(r"(?:Packaging|Package)\s*[:\-]?\s*([^\n\r;]{5,100})", full_text, re.I)
    if pkg_match:
        res["packaging_details"] = pkg_match.group(1).strip()

    # 7. Technical characteristics (e.g. Schedule B specs)
    specs = []
    for spec_pat in [
        r"Viscosity\s*(?:at\s*25°C)?\s*[:\-]?\s*([^\n\r;]+)",
        r"Epoxy\s*value\s*[:\-]?\s*([^\n\r;]+)",
        r"Purity\s*[:\-]?\s*([^\n\r;]+)",
        r"Moisture\s*content\s*[:\-]?\s*([^\n\r;]+)",
        r"Specific\s*gravity\s*[:\-]?\s*([^\n\r;]+)",
        r"Tensile\s*strength\s*[:\-]?\s*([^\n\r;]+)",
        r"Yield\s*strength\s*[:\-]?\s*([^\n\r;]+)",
        r"Appearance\s*[:\-]?\s*([^\n\r;]+)",
    ]:
        sm = re.search(spec_pat, full_text, re.I)
        if sm:
            specs.append(sm.group(0).strip())
    if specs:
        res["technical_characteristics"] = "; ".join(specs)

    # 8. Dates
    eff_match = re.search(r"(?:Effective\s*Date|Contract\s*Term)\s*[:\-]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", full_text, re.I)
    if eff_match:
        res["contract_effective_date"] = eff_match.group(1).strip()

    return res


class ContractPricingExtractor:
    """Extracts raw material pricing and specification details from active contracts."""

    async def _get_recorded_price_fallback(
        self, db: AsyncSession, contract: Contract, supplier_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return a price already recorded in the relational system.

        A PDF can be image-only or have a badly extracted table. In that case,
        use an explicit contract-product price first, then a PO associated with
        this contract, and finally a previously completed benchmark run. These
        are stored commercial records, not generated estimates.
        """
        contract_product_stmt = (
            select(ContractProduct, Product)
            .join(Product, ContractProduct.product_id == Product.product_id)
            .where(
                ContractProduct.contract_id == contract.contract_id,
                ContractProduct.contracted_unit_price.is_not(None),
                ContractProduct.contracted_unit_price > 0,
            )
            .order_by(ContractProduct.price_valid_from.desc().nullslast())
        )
        row = (await db.execute(contract_product_stmt)).first()
        if row:
            contract_product, product = row
            return {
                "material_name": product.product_name,
                "product_code": product.product_id,
                "technical_characteristics": product.description,
                "contract_unit_price": float(contract_product.contracted_unit_price),
                "currency": contract_product.currency or product.currency or "INR",
                "unit_of_measurement": product.package_unit or "unit",
                "contract_quantity": contract_product.minimum_annual_quantity,
                "annual_estimated_quantity": contract_product.minimum_annual_quantity,
                "evidence": f"Recorded contract-product price ({contract.contract_id})",
            }

        po_item_stmt = (
            select(PurchaseOrderItem, PurchaseOrder, Product)
            .join(PurchaseOrder, PurchaseOrderItem.order_id == PurchaseOrder.order_id)
            .join(Product, PurchaseOrderItem.product_id == Product.product_id)
            .where(
                PurchaseOrder.supplier_id == supplier_id,
                PurchaseOrder.contract_id == contract.contract_id,
                PurchaseOrderItem.unit_price > 0,
            )
            .order_by(PurchaseOrder.order_date.desc())
        )
        row = (await db.execute(po_item_stmt)).first()
        if row:
            item, order, product = row
            return {
                "material_name": product.product_name,
                "product_code": product.product_id,
                "technical_characteristics": product.description,
                "contract_unit_price": float(item.unit_price),
                "currency": order.currency or product.currency or "INR",
                "unit_of_measurement": product.package_unit or "unit",
                "contract_quantity": item.quantity,
                "annual_estimated_quantity": item.quantity,
                "evidence": f"Latest purchase order {order.order_id} linked to {contract.contract_id}",
            }

        run_stmt = (
            select(PriceResearchRun)
            .where(
                PriceResearchRun.supplier_id == supplier_id,
                PriceResearchRun.contract_id == contract.contract_id,
                PriceResearchRun.contract_price.is_not(None),
                PriceResearchRun.contract_price > 0,
            )
            .order_by(PriceResearchRun.created_at.desc())
        )
        run = (await db.execute(run_stmt)).scalars().first()
        if run:
            return {
                "material_name": run.material_name,
                "grade": run.grade,
                "product_code": run.product_code,
                "technical_characteristics": run.technical_characteristics,
                "contract_unit_price": float(run.contract_price),
                "currency": run.contract_currency or "INR",
                "unit_of_measurement": run.contract_unit or "unit",
                "contract_quantity": float(run.contract_quantity) if run.contract_quantity else None,
                "annual_estimated_quantity": float(run.annual_quantity) if run.annual_quantity else None,
                "evidence": f"Previously completed market research run {run.id}",
            }
        return None

    async def extract_pricing_details(
        self,
        db: AsyncSession,
        supplier_id: str,
        contract_id: Optional[str] = None,
    ) -> ContractPricingDetails:
        """
        Extract structured contract pricing and material specs for a supplier.
        Reuses existing PostgreSQL models and hybrid vector/chunk pipeline.
        """
        # 1. Fetch Contract Record
        stmt = select(Contract)
        if contract_id:
            stmt = stmt.where(Contract.contract_id == contract_id)
        else:
            stmt = stmt.where(Contract.supplier_id == supplier_id).order_by(Contract.created_at.desc())
        
        result = await db.execute(stmt)
        contract = result.scalars().first()
        if not contract:
            raise ValueError(f"No contract found for supplier {supplier_id}")

        # Fetch supplier name
        supplier_stmt = select(Supplier).where(Supplier.supplier_id == supplier_id)
        supplier_res = await db.execute(supplier_stmt)
        supplier = supplier_res.scalars().first()
        supplier_name = supplier.supplier_name if supplier else (contract.supplier_id or "")

        # 2. Extract Document Text
        full_text = ""
        evidence_sources = []
        if contract.document_data:
            pages = parse_document(contract.document_filename or "contract.pdf", contract.document_data)
            full_text = "\n\n".join(p.get("text", "") for p in pages if p.get("text"))
            evidence_sources.append(f"Cloud DB document: {contract.document_filename or contract.contract_id} ({len(pages)} pages)")
        elif contract.document_path:
            import os
            if os.path.isfile(contract.document_path):
                with open(contract.document_path, "rb") as f:
                    pages = parse_document(os.path.basename(contract.document_path), f.read())
                    full_text = "\n\n".join(p.get("text", "") for p in pages if p.get("text"))
                    evidence_sources.append(f"Disk document: {os.path.basename(contract.document_path)} ({len(pages)} pages)")

        # 3. Hybrid RAG targeted retrieval if text is long
        retrieved_context = full_text
        if len(full_text) > 8000:
            rag_chunks = hybrid_retriever.retrieve(
                query="Schedule A product commercial details unit price per kg quantity delivery Incoterms Schedule B specifications",
                supplier_id=supplier_id,
                top_k=8,
            )
            if rag_chunks:
                retrieved_context = "\n\n".join(
                    f"--- Page {c.get('page_number', 1)}, Section: {c.get('section_title', '')} ---\n{c.get('text', '')}"
                    for c in rag_chunks
                )
                evidence_sources.extend([
                    f"Page {c.get('page_number', 1)}: {c.get('section_title', 'Terms')}" for c in rag_chunks[:4]
                ])

        # 4. LLM Structured Extraction (with Groq)
        extracted_dict: Optional[Dict[str, Any]] = None
        if settings.GROQ_API_KEY and retrieved_context:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                prompt = f"""Extract commercial raw material details from this contract:
SUPPLIER: {supplier_name}
CONTRACT ID: {contract.contract_id}
CONTRACT TITLE: {contract.contract_title or 'Master Supply Agreement'}

CONTRACT EXCERPTS:
{retrieved_context[:10000]}
"""
                resp = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": SYSTEM_EXTRACTION_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    model=settings.LLM_MODEL_NAME,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                extracted_dict = json.loads(resp.choices[0].message.content)
            except Exception as e:
                logger.warning(f"Groq LLM extraction for pricing details encountered error: {e}")
                extracted_dict = None

        # 5. Deterministic Heuristic Fallback & Merging
        heuristic_data = _heuristic_extract_pricing(full_text or retrieved_context, supplier_name)
        if heuristic_data["contract_unit_price"] <= 0:
            recorded_price = await self._get_recorded_price_fallback(db, contract, supplier_id)
            if recorded_price:
                for key, value in recorded_price.items():
                    if key != "evidence" and value is not None:
                        heuristic_data[key] = value
                evidence_sources.append(recorded_price["evidence"])
        if not extracted_dict or not extracted_dict.get("material_name") or extracted_dict.get("contract_unit_price", 0) <= 0:
            extracted_dict = heuristic_data
        else:
            # Merge any missing fields from heuristic
            for key, val in heuristic_data.items():
                if key != "evidence_sources" and (not extracted_dict.get(key) or extracted_dict.get(key) in ("null", None, 0.0)):
                    extracted_dict[key] = val

        # Ensure numeric values are valid
        unit_price = parse_numeric_price(extracted_dict.get("contract_unit_price")) or 0.0
        annual_qty = (
            parse_numeric_price(extracted_dict.get("annual_estimated_quantity"))
            or parse_numeric_price(extracted_dict.get("contract_quantity"))
            or 0.0
        )
        curr = (extracted_dict.get("currency") or "INR").upper()
        if curr == "₹": curr = "INR"

        return ContractPricingDetails(
            material_name=extracted_dict.get("material_name") or "Industrial Material",
            grade=extracted_dict.get("grade"),
            product_code=extracted_dict.get("product_code"),
            technical_characteristics=extracted_dict.get("technical_characteristics"),
            contract_unit_price=unit_price,
            currency=curr,
            unit_of_measurement=extracted_dict.get("unit_of_measurement") or "kg",
            contract_quantity=extracted_dict.get("contract_quantity") or annual_qty,
            annual_estimated_quantity=annual_qty,
            contract_effective_date=extracted_dict.get("contract_effective_date") or (contract.effective_date.isoformat() if contract.effective_date else None),
            contract_expiry_date=extracted_dict.get("contract_expiry_date") or (contract.expiry_date.isoformat() if contract.expiry_date else None),
            delivery_location=extracted_dict.get("delivery_location"),
            incoterms=extracted_dict.get("incoterms"),
            tax_inclusion=extracted_dict.get("tax_inclusion"),
            packaging_details=extracted_dict.get("packaging_details"),
            supplier_name=supplier_name,
            contract_id=contract.contract_id,
            contract_title=contract.contract_title or contract.document_filename,
            evidence_sources=evidence_sources or [f"Contract {contract.contract_id}"],
        )


contract_pricing_extractor = ContractPricingExtractor()
