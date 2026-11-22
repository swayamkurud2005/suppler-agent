"""
AI-Powered Supplier Information Extraction Service.
Extracts legal supplier company details, business category, location, and verified contact
information from uploaded contracts (PDF/DOCX) using hybrid RAG retrieval and LLM structured output.
"""

import os
import re
import json
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.models.models import Supplier, Contract, DocumentIngestionLog
from app.services.document_parser import parse_document, calculate_file_hash
from app.services.chunking import chunk_pages
from app.services.hybrid_retriever import SimpleBM25

logger = logging.getLogger("supplier_extractor")

# Standard allowed business categories aligned with Supplier 360 taxonomy
VALID_CATEGORIES = [
    "Raw Materials",
    "Electronics & Semiconductors",
    "Precision Machining",
    "Hydraulics & Fluid Power",
    "Packaging & Logistics",
    "Fasteners & Hardware",
    "Other / General",
]

EXTRACTION_SYSTEM_PROMPT = """You are Supplier 360's Contract Intelligence Agent.
Your objective is to accurately extract the legal SUPPLIER / VENDOR / SELLER partner details from a contract document.

CRITICAL PROCUREMENT RULES:
1. PARTY DISTINCTION (DO NOT CONFUSE BUYER AND SUPPLIER):
   - A contract is between a Buyer/Customer and a Supplier/Vendor/Seller.
   - The Buyer is the procurement party purchasing goods or services (e.g. Enterprise Procurement, ACME Corp, etc.).
   - The Supplier is the contracting party delivering, manufacturing, or selling the goods or services.
   - Extract the SUPPLIER's information, NOT the Buyer/Customer's information!
   - If in doubt between two parties, analyze their respective obligations (who sells/supplies vs who pays/receives).

2. ZERO HALLUCINATION & FACTUAL CITATIONS:
   - Only extract information explicitly stated in the provided text.
   - If a field (e.g. email, phone, contact person) is NOT explicitly mentioned for the supplier, return null for value, 0.0 for confidence, and null for source.
   - NEVER invent or guess email addresses, phone numbers, or representatives.
   - For every extracted field, cite the source clearly (e.g., "Contract page 1, Preamble / Parties section" or "Contract page 8, Notices").

3. CATEGORY SELECTION:
   - Select the most appropriate category from:
     ["Raw Materials", "Electronics & Semiconductors", "Precision Machining", "Hydraulics & Fluid Power", "Packaging & Logistics", "Fasteners & Hardware", "Other / General"]
   - Base this on the goods, products, or scope of supply described in the contract.
   - If not clearly specified, return "Other / General" or null.

4. MULTIPLE CANDIDATES:
   - If multiple distinct supplier entities, subcontractors, or parent/subsidiary entities are identified as potential suppliers, list them under multiple_candidates.
"""


def _normalize_extracted_category(category_raw: Optional[str]) -> str:
    """Normalize extracted category against known taxonomy."""
    if not category_raw:
        return "Raw Materials"
    cat_lower = category_raw.lower()
    for cat in VALID_CATEGORIES:
        if cat.lower() in cat_lower or cat_lower in cat.lower():
            return cat
    if any(k in cat_lower for k in ["metal", "steel", "chemical", "material", "plastic", "alloy"]):
        return "Raw Materials"
    if any(k in cat_lower for k in ["electronic", "semiconductor", "pcb", "sensor", "chip"]):
        return "Electronics & Semiconductors"
    if any(k in cat_lower for k in ["machining", "cnc", "tooling", "fabrication", "lathe"]):
        return "Precision Machining"
    if any(k in cat_lower for k in ["hydraulic", "fluid", "pneumatic", "valve", "pump"]):
        return "Hydraulics & Fluid Power"
    if any(k in cat_lower for k in ["packaging", "carton", "box", "logistics", "freight"]):
        return "Packaging & Logistics"
    if any(k in cat_lower for k in ["fastener", "screw", "bolt", "nut", "hardware"]):
        return "Fasteners & Hardware"
    return "Other / General"


def deterministic_heuristic_extract(
    pages: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    High-precision heuristic and regex extraction fallback.
    Analyzes preambles, recitals, notices, and signature blocks.
    """
    full_text = "\n\n".join(p["text"] for p in pages)
    first_page_text = pages[0]["text"] if pages else full_text[:4000]
    
    # 1. Identify Supplier Name
    supplier_name = None
    supplier_conf = 0.0
    supplier_source = None
    multiple_candidates = []

    # Patterns matching "by and between BUYER ... and SUPPLIER" or "SUPPLIER: [Company Name]"
    # Common legal structures:
    # "... between Buyer Inc. ... and [Supplier Name] (hereinafter 'Supplier')"
    # "1. PARTIES: ... Supplier: Acme Corp"
    party_patterns = [
        r"(?:between|among)\s+([A-Za-z0-9\s,.\-&]+?)\s+(?:and|&)\s+([A-Za-z0-9\s,.\-&]+?)(?:,\s*hereinafter|\s*\(hereinafter|\s*as\s+of|\s*dated)",
        r"(?:SUPPLIER|VENDOR|SELLER|CONTRACTOR)\s*:\s*([A-Za-z0-9\s,.\-&]{3,80})(?:\n|\r|,|;|\()",
        r"(?:hereinafter\s+(?:called|referred\s+to\s+as)\s+(?:the\s+)?[\"'](?:Supplier|Vendor|Seller)[\"'][\s,]*([A-Za-z0-9\s,.\-&]{3,80}))",
        r"([A-Za-z0-9\s,.\-&]{3,80})\s+(?:\(hereinafter\s+(?:called|referred\s+to\s+as)\s+(?:the\s+)?[\"'](?:Supplier|Vendor|Seller)[\"']\))",
    ]

    for pat in party_patterns:
        match = re.search(pat, first_page_text, re.IGNORECASE)
        if match:
            groups = [g.strip() for g in match.groups() if g and g.strip()]
            if len(groups) == 2:
                p1, p2 = groups[0], groups[1]
                # Determine which party is likely the supplier
                # Often the second party in "between Buyer and Supplier" is the vendor
                candidate_supplier = p2
                candidate_buyer = p1
                if any(k in p1.lower() for k in ["supplier", "vendor", "mfg", "technologies", "precision", "industries"]):
                    candidate_supplier = p1
                    candidate_buyer = p2
                supplier_name = re.sub(r"[\n\r]+", " ", candidate_supplier).strip()
                supplier_conf = 0.88
                supplier_source = f"Contract page {pages[0]['page']}, Parties preamble"
                multiple_candidates.append({"name": candidate_supplier, "role": "Supplier / Contractor", "description": "Identified as second contracting party in agreement recitals"})
                multiple_candidates.append({"name": candidate_buyer, "role": "Buyer / Customer", "description": "Identified as first contracting party in agreement recitals"})
                break
            elif len(groups) == 1:
                cand = re.sub(r"[\n\r]+", " ", groups[0]).strip()
                cand = re.sub(r"^(?:the\s+|a\s+)", "", cand, flags=re.I)
                if len(cand) > 3 and not any(cand.lower().startswith(x) for x in ["buyer", "customer", "agreement", "party"]):
                    supplier_name = cand
                    supplier_conf = 0.90
                    supplier_source = f"Contract page {pages[0]['page']}, Parties section"
                    break

    # Title fallback if no party match
    if not supplier_name:
        for p in pages[:2]:
            lines = [line.strip() for line in p["text"].split("\n") if line.strip()]
            for line in lines:
                if re.search(r"\b(pvt|ltd|llc|inc|corp|corporation|gmbh|co\.|limited)\b", line, re.I):
                    if not any(k in line.lower() for k in ["buyer", "enterprise procurement", "confidential"]):
                        supplier_name = line[:80].strip()
                        supplier_conf = 0.70
                        supplier_source = f"Contract page {p['page']}, Entity heading"
                        break
            if supplier_name:
                break

    # 2. Location / Country
    location = None
    location_conf = 0.0
    location_source = None
    loc_match = re.search(
        r"(?:registered\s+office|principal\s+place\s+of\s+business|located\s+at|having\s+(?:its\s+)?address\s+at)\s*[:\-]?\s*([^\n\r;]{5,120})",
        first_page_text,
        re.I,
    )
    if loc_match:
        loc_str = loc_match.group(1).strip()
        loc_clean = re.sub(r"\s+", " ", loc_str)
        location = loc_clean
        location_conf = 0.85
        location_source = f"Contract page {pages[0]['page']}, Registered Address"
    else:
        # Check for city/country patterns
        city_match = re.search(r"\b(Pune|Mumbai|Delhi|Bengaluru|Bangalore|Chennai|Hyderabad|Ahmedabad|Coimbatore|Kolkata|Berlin|Munich|London|Chicago|Tokyo|Singapore)(?:,\s*([A-Za-z\s]+))?", first_page_text, re.I)
        if city_match:
            location = city_match.group(0).strip()
            location_conf = 0.75
            location_source = f"Contract page {pages[0]['page']}, Jurisdiction / Location"

    # 3. Notices & Contact info (Email, Phone, Contact Person)
    contact_email = None
    email_conf = 0.0
    email_source = None

    contact_phone = None
    phone_conf = 0.0
    phone_source = None

    contact_person = None
    person_conf = 0.0
    person_source = None

    # Search for notices section or full text
    notices_chunks = [c for c in chunks if "notice" in c.get("text", "").lower() or "communication" in c.get("text", "").lower()]
    search_scope_chunks = notices_chunks if notices_chunks else chunks

    # Email regex
    email_regex = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b")
    # Phone regex
    phone_regex = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,5}\b")

    for c in search_scope_chunks:
        text = c.get("text", "")
        # Find emails
        emails = email_regex.findall(text)
        if emails and not contact_email:
            # Filter out buyer or standard placeholders
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ["buyer", "customer", "legal@", "procurement@company"])]
            chosen_email = valid_emails[0] if valid_emails else emails[0]
            contact_email = chosen_email
            email_conf = 0.92
            email_source = f"Contract page {c.get('page_number', 1)}, {c.get('section_title', 'Notices')}"

        # Find phones
        if not contact_phone:
            phones = phone_regex.findall(text)
            # Filter strings that look like dates or numbers
            valid_phones = [p.strip() for p in phones if len(re.sub(r"\D", "", p)) >= 10]
            if valid_phones:
                contact_phone = valid_phones[0]
                phone_conf = 0.85
                phone_source = f"Contract page {c.get('page_number', 1)}, {c.get('section_title', 'Notices')}"

        # Contact person / Attention
        if not contact_person:
            attn_match = re.search(r"(?:Attention|Attn|Kind\s+Attn|Representative|Contact\s+Person)\s*[:\-]\s*(?:Mr\.|Ms\.|Dr\.)?\s*([A-Za-z\s]{3,40})", text, re.I)
            if attn_match:
                name_cand = attn_match.group(1).strip()
                if not any(x in name_cand.lower() for x in ["buyer", "legal department", "director", "manager"]):
                    contact_person = name_cand
                    person_conf = 0.88
                    person_source = f"Contract page {c.get('page_number', 1)}, Notices section"

    # Check signature blocks for signatory name if contact person not found
    if not contact_person:
        for p in reversed(pages):
            sig_match = re.search(r"(?:By|Name|Signed\s+by)\s*[:\-]\s*(?:Mr\.|Ms\.|Dr\.)?\s*([A-Za-z\s.]{3,40})(?:\n|\r|Title|Designation)", p["text"], re.I)
            if sig_match:
                cand = sig_match.group(1).strip()
                if len(cand) > 3 and not any(x in cand.lower() for x in ["buyer", "authorized", "signature", "date"]):
                    contact_person = cand
                    person_conf = 0.82
                    person_source = f"Contract page {p['page']}, Signature block"
                    break

    # 4. Category
    category = "Raw Materials"
    category_conf = 0.80
    category_source = f"Contract page {pages[0]['page']}, Goods & Scope of Supply"
    for cat in VALID_CATEGORIES:
        if cat == "Other / General":
            continue
        keywords = cat.lower().replace("&", "").split()
        if any(kw in full_text.lower() for kw in keywords if len(kw) > 3):
            category = cat
            category_conf = 0.88
            break

    return {
        "supplier_name": {
            "value": supplier_name,
            "confidence": supplier_conf,
            "source": supplier_source,
        },
        "category": {
            "value": category,
            "confidence": category_conf,
            "source": category_source,
        },
        "location": {
            "value": location,
            "confidence": location_conf,
            "source": location_source,
        },
        "contact_person": {
            "value": contact_person,
            "confidence": person_conf,
            "source": person_source,
        },
        "contact_email": {
            "value": contact_email,
            "confidence": email_conf,
            "source": email_source,
        },
        "contact_phone": {
            "value": contact_phone,
            "confidence": phone_conf,
            "source": phone_source,
        },
        "multiple_candidates": multiple_candidates,
    }


class SupplierExtractorService:
    """End-to-end contract analysis and supplier metadata extraction service."""

    async def extract_from_contract(
        self,
        filename: str,
        file_bytes: bytes,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Orchestrates full RAG contract analysis to extract supplier details.
        Step 1: Document validation & parsing
        Step 2: Clause-aware chunking & targeted retrieval
        Step 3: Structured LLM extraction (or robust fallback)
        Step 4: Duplicate supplier detection against PostgreSQL
        Step 5: Cache contract file token for seamless supplier creation
        """
        # Validate format
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".pdf", ".docx", ".doc", ".txt"}:
            raise ValueError(f"Unsupported document format '{ext}'. Please upload a PDF or DOCX file.")

        # Validate size
        if len(file_bytes) > settings.max_upload_bytes:
            raise ValueError(f"File exceeds maximum upload size of {settings.MAX_UPLOAD_SIZE_MB}MB.")
        if len(file_bytes) == 0:
            raise ValueError("Uploaded document is empty.")

        # Step 1: Parse Document Text
        try:
            pages = parse_document(filename, file_bytes)
        except Exception as e:
            raise ValueError(f"Could not parse document: {str(e)}. File may be corrupted or password-protected.")

        full_text = "\n\n".join(p["text"] for p in pages if p.get("text", "").strip())
        if not full_text.strip():
            raise ValueError("The uploaded document contains no readable text. Scanned images without OCR or password-protected PDFs cannot be processed.")

        # Step 2: Clause-Aware Chunking & Targeted RAG Retrieval
        contract_temp_id = f"TMP-{uuid.uuid4().hex[:8].upper()}"
        chunks = chunk_pages(
            pages=pages,
            contract_id=contract_temp_id,
            supplier_id="NEW_ONBOARDING",
            document_name=filename,
        )

        # Build in-memory BM25 index over the chunks for targeted retrieval
        bm25 = SimpleBM25()
        bm25.fit(chunks)

        # Targeted retrieval for key supplier onboarding topics
        targeted_queries = [
            ("parties_preamble", "agreement by and between Supplier Vendor Seller Customer registered office address", 4),
            ("notices_contacts", "notices communications attention email telephone phone contact person address", 4),
            ("scope_supply", "scope of supply products goods specifications manufacture category", 3),
            ("signature_block", "in witness whereof authorized representative signatory name title by signature", 3),
        ]

        retrieved_chunk_ids = set()
        retrieved_chunks = []
        for q_name, query, limit in targeted_queries:
            results = bm25.search(query=query, limit=limit)
            for hit in results:
                cid = hit.get("chunk_id")
                if cid not in retrieved_chunk_ids:
                    retrieved_chunk_ids.add(cid)
                    retrieved_chunks.append(hit)

        # Always include first 2 pages chunks (preamble & recitals are crucial)
        for c in chunks:
            if c.get("page_number", 1) <= 2 and c.get("chunk_id") not in retrieved_chunk_ids:
                retrieved_chunk_ids.add(c.get("chunk_id"))
                retrieved_chunks.append(c)

        # Step 3: AI Information Extraction with Groq LLM
        extracted_data = None
        if settings.GROQ_API_KEY:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=settings.GROQ_API_KEY)

                # Format retrieved evidence
                evidence_text_list = []
                for idx, c in enumerate(retrieved_chunks, 1):
                    evidence_text_list.append(
                        f"--- EVIDENCE EXCERPT {idx} [Page {c.get('page_number', 1)}, Section: '{c.get('section_title', 'Overview')}'] ---\n{c.get('text', '')}"
                    )
                context_block = "\n\n".join(evidence_text_list)

                prompt = f"""Extract the SUPPLIER partner details from this contract.
Remember:
- Distinguish the BUYER from the SUPPLIER. Do NOT extract the buyer/customer company name!
- If a field is not found in the text, set value to null and confidence to 0.0.
- Extract:
  1. supplier_name: Legal name of the supplier company
  2. category: One of ["Raw Materials", "Electronics & Semiconductors", "Precision Machining", "Hydraulics & Fluid Power", "Packaging & Logistics", "Fasteners & Hardware", "Other / General"]
  3. location: Registered office or primary business address/city/country
  4. contact_person: Authorized representative or primary contact
  5. contact_email: Explicitly stated supplier or notices email
  6. contact_phone: Explicitly stated supplier or notices telephone/phone number
  7. multiple_candidates: Any other potential supplier parties or subcontractors identified (or empty array)

DOCUMENT NAME: {filename}

=== RELEVANT CONTRACT SECTIONS ===
{context_block[:12000]}

Respond ONLY with a valid JSON object matching this exact schema:
{{
  "supplier_name": {{ "value": "string or null", "confidence": float, "source": "string or null" }},
  "category": {{ "value": "string or null", "confidence": float, "source": "string or null" }},
  "location": {{ "value": "string or null", "confidence": float, "source": "string or null" }},
  "contact_person": {{ "value": "string or null", "confidence": float, "source": "string or null" }},
  "contact_email": {{ "value": "string or null", "confidence": float, "source": "string or null" }},
  "contact_phone": {{ "value": "string or null", "confidence": float, "source": "string or null" }},
  "multiple_candidates": [
    {{ "name": "string", "role": "string", "description": "string" }}
  ]
}}
"""
                response = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    model=settings.LLM_MODEL_NAME,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                raw_json = response.choices[0].message.content
                extracted_data = json.loads(raw_json)
                logger.info("Successfully extracted supplier details via Groq LLM.")
            except Exception as e:
                logger.warning(f"Groq LLM supplier extraction failed ({e}), using deterministic heuristic fallback.")
                extracted_data = None

        if not extracted_data or not extracted_data.get("supplier_name", {}).get("value"):
            fallback_res = deterministic_heuristic_extract(pages, chunks)
            if not extracted_data:
                extracted_data = fallback_res
            else:
                # Merge fallback for any missing values
                for k, v in fallback_res.items():
                    if k not in extracted_data or not extracted_data[k] or not extracted_data[k].get("value"):
                        extracted_data[k] = v

        # Normalize category
        cat_val = extracted_data.get("category", {}).get("value")
        if cat_val:
            extracted_data["category"]["value"] = _normalize_extracted_category(cat_val)
        else:
            extracted_data["category"] = {
                "value": "Raw Materials",
                "confidence": 0.5,
                "source": "Default category fallback",
            }

        # Step 4: Duplicate Supplier Check in PostgreSQL
        supplier_name_val = extracted_data.get("supplier_name", {}).get("value")
        is_duplicate = False
        existing_supplier_info = None

        if supplier_name_val and supplier_name_val.strip():
            clean_name = supplier_name_val.strip().lower()
            stmt = select(Supplier).where(func.lower(Supplier.supplier_name) == clean_name)
            res = await db.execute(stmt)
            existing_supplier = res.scalars().first()

            if not existing_supplier:
                # Try partial match if name has common prefixes/suffixes
                base_name = re.sub(r"\b(pvt|ltd|llc|inc|corp|co\.|limited|technologies|systems)\b", "", clean_name, flags=re.I).strip()
                if len(base_name) > 4:
                    stmt2 = select(Supplier).where(Supplier.supplier_name.ilike(f"%{base_name}%"))
                    res2 = await db.execute(stmt2)
                    existing_supplier = res2.scalars().first()

            if existing_supplier:
                is_duplicate = True
                existing_supplier_info = {
                    "id": existing_supplier.supplier_id,
                    "name": existing_supplier.supplier_name,
                    "category": existing_supplier.category,
                    "location": existing_supplier.location,
                    "status": existing_supplier.status,
                }

        # Step 5: Cache uploaded file to temporary directory so it can be committed on supplier creation
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        file_token = f"TEMP_{uuid.uuid4().hex[:12]}_{calculate_file_hash(file_bytes)[:8]}"
        safe_filename = re.sub(r"[^\w\-.]", "_", filename)
        temp_filepath = os.path.join(settings.UPLOAD_DIR, f"{file_token}_{safe_filename}")
        with open(temp_filepath, "wb") as f:
            f.write(file_bytes)

        return {
            "supplier_name": extracted_data.get("supplier_name", {"value": None, "confidence": 0, "source": None}),
            "category": extracted_data.get("category", {"value": "Raw Materials", "confidence": 0.5, "source": None}),
            "location": extracted_data.get("location", {"value": None, "confidence": 0, "source": None}),
            "contact_person": extracted_data.get("contact_person", {"value": None, "confidence": 0, "source": None}),
            "contact_email": extracted_data.get("contact_email", {"value": None, "confidence": 0, "source": None}),
            "contact_phone": extracted_data.get("contact_phone", {"value": None, "confidence": 0, "source": None}),
            "multiple_candidates": extracted_data.get("multiple_candidates", []),
            "is_duplicate": is_duplicate,
            "existing_supplier": existing_supplier_info,
            "document_token": file_token,
            "filename": filename,
            "file_size": len(file_bytes),
            "pages_parsed": len(pages),
            "chunks_extracted": len(chunks),
        }

    async def get_available_documents(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        List all contract documents available in the system (from disk storage and DB tables).
        Enables users to extract supplier info without re-uploading documents.
        """
        documents_map = {}

        # 1. Check contracts table in PostgreSQL
        try:
            contracts_res = await db.execute(select(Contract))
            contracts = contracts_res.scalars().all()
            for c in contracts:
                doc_name = None
                if c.document_path and os.path.isfile(c.document_path):
                    doc_name = os.path.basename(c.document_path)
                elif c.contract_title:
                    doc_name = c.contract_title
                if doc_name:
                    file_size = 0
                    if c.document_path and os.path.isfile(c.document_path):
                        file_size = os.path.getsize(c.document_path)
                    clean_name = re.sub(r"^CTR-[A-Z0-9]+_", "", doc_name)
                    documents_map[doc_name] = {
                        "filename": doc_name,
                        "displayName": clean_name.replace("_", " ").replace(".pdf", ""),
                        "contractId": c.contract_id,
                        "supplierId": c.supplier_id,
                        "fileSize": file_size,
                        "uploadedDate": c.created_at.strftime("%Y-%m-%d") if c.created_at else None,
                        "source": "contract_record",
                    }
        except Exception as e:
            logger.warning(f"Error reading contracts for available documents: {e}")

        # 2. Check document_ingestion_log
        try:
            logs_res = await db.execute(select(DocumentIngestionLog))
            logs = logs_res.scalars().all()
            for log in logs:
                doc_name = log.document_name
                if doc_name and doc_name not in documents_map:
                    clean_name = re.sub(r"^CTR-[A-Z0-9]+_", "", doc_name)
                    documents_map[doc_name] = {
                        "filename": doc_name,
                        "displayName": clean_name.replace("_", " ").replace(".pdf", ""),
                        "contractId": log.contract_id,
                        "supplierId": None,
                        "fileSize": 0,
                        "uploadedDate": log.started_at.strftime("%Y-%m-%d") if log.started_at else None,
                        "source": "ingestion_log",
                    }
        except Exception as e:
            logger.warning(f"Error reading ingestion logs for available documents: {e}")

        # 3. Check UPLOAD_DIR on disk for any stored PDFs/DOCXs
        upload_dir = settings.UPLOAD_DIR
        if os.path.isdir(upload_dir):
            for fname in os.listdir(upload_dir):
                if fname.lower().endswith((".pdf", ".docx", ".doc", ".txt")) and not fname.startswith("TEMP_"):
                    if fname not in documents_map:
                        fpath = os.path.join(upload_dir, fname)
                        size = os.path.getsize(fpath) if os.path.isfile(fpath) else 0
                        clean_name = re.sub(r"^CTR-[A-Z0-9]+_", "", fname)
                        documents_map[fname] = {
                            "filename": fname,
                            "displayName": clean_name.replace("_", " ").replace(".pdf", ""),
                            "contractId": fname.split("_")[0] if fname.startswith("CTR-") else None,
                            "supplierId": None,
                            "fileSize": size,
                            "uploadedDate": None,
                            "source": "disk_storage",
                        }

        return list(documents_map.values())

    async def extract_from_existing_document(
        self,
        db: AsyncSession,
        document_name: Optional[str] = None,
        contract_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract supplier details from an already-uploaded document without requiring the user to re-upload.
        Resolves the document by supplier_id, contract_id, or document_name.
        """
        target_path = None
        target_filename = document_name or "contract.pdf"

        # Strategy 1: Find by supplier_id
        if supplier_id:
            stmt = select(Contract).where(Contract.supplier_id == supplier_id).order_by(Contract.created_at.desc())
            contract = (await db.execute(stmt)).scalars().first()
            if contract and contract.document_path and os.path.isfile(contract.document_path):
                target_path = contract.document_path
                target_filename = os.path.basename(target_path)
            elif contract and contract.contract_title:
                target_filename = contract.contract_title

        # Strategy 2: Find by contract_id
        if not target_path and contract_id:
            stmt = select(Contract).where(Contract.contract_id == contract_id)
            contract = (await db.execute(stmt)).scalars().first()
            if contract and contract.document_path and os.path.isfile(contract.document_path):
                target_path = contract.document_path
                target_filename = os.path.basename(target_path)

        # Strategy 3: Find by document_name in UPLOAD_DIR
        if not target_path and document_name:
            candidate_path = os.path.join(settings.UPLOAD_DIR, document_name)
            if os.path.isfile(candidate_path):
                target_path = candidate_path
                target_filename = document_name
            elif os.path.isdir(settings.UPLOAD_DIR):
                for fname in os.listdir(settings.UPLOAD_DIR):
                    if document_name in fname or fname in document_name:
                        target_path = os.path.join(settings.UPLOAD_DIR, fname)
                        target_filename = fname
                        break

        if not target_path or not os.path.isfile(target_path):
            raise ValueError(f"Could not locate document file for extraction (contract_id={contract_id}, document_name={document_name}, supplier_id={supplier_id}).")

        with open(target_path, "rb") as f:
            file_bytes = f.read()

        res = await self.extract_from_contract(
            filename=target_filename,
            file_bytes=file_bytes,
            db=db,
        )
        res["is_existing_document"] = True
        return res


supplier_extractor = SupplierExtractorService()
