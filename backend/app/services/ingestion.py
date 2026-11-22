"""
Full document ingestion pipeline:
File storage -> SHA-256 deduplication -> Parsing -> Chunking -> Vector Indexing ->
Structured LLM Extraction -> Database persistence.
"""

import os
import time
from datetime import datetime, date
from decimal import Decimal
import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.models import Contract, ContractTerms, DocumentIngestionLog, Supplier
from app.services.document_parser import parse_document, calculate_file_hash
from app.services.chunking import chunk_pages
from app.services.vector_store import vector_store
from app.services.extraction import extract_contract_terms

logger = logging.getLogger("ingestion")


class IngestionService:
    """Orchestrates end-to-end ingestion of supplier contracts."""

    async def ingest_contract(
        self,
        db: AsyncSession,
        filename: str,
        file_bytes: bytes,
        supplier_id: str,
    ) -> dict:
        start_time = time.time()
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

        if not supplier_id:
            raise ValueError("supplier_id is required")
        supplier = (await db.execute(select(Supplier).where(Supplier.supplier_id == supplier_id))).scalars().first()
        if not supplier:
            raise ValueError("Supplier not found; create the supplier before uploading a contract")
        if not file_bytes:
            raise ValueError("The uploaded file is empty")
        if len(file_bytes) > settings.max_upload_bytes:
            raise ValueError(f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB upload limit")
        extension = os.path.splitext(filename)[1].lower()
        if extension not in {".pdf", ".docx", ".txt"}:
            raise ValueError("Only PDF, DOCX, and TXT contract files are supported")

        # 1. Compute Hash and Check Duplication
        doc_hash = calculate_file_hash(file_bytes)
        existing_stmt = select(Contract).where(Contract.document_hash == doc_hash)
        existing_contract = (await db.execute(existing_stmt)).scalars().first()
        if existing_contract:
            if existing_contract.supplier_id != supplier_id:
                raise ValueError("This document is already associated with a different supplier")
            return {
                "status": "duplicate",
                "contract_id": existing_contract.contract_id,
                "document_name": filename,
                "chunks_indexed": 0,
                "fields_extracted": 0,
                "processing_time_seconds": round(time.time() - start_time, 2),
                "message": "This contract was already ingested; existing vectors were retained.",
            }

        contract_id = f"CTR-{uuid.uuid4().hex[:8].upper()}"
        save_path = os.path.join(settings.UPLOAD_DIR, f"{contract_id}_{filename}")
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        # 2. Parse Pages before any vector writes.
        pages = parse_document(filename, file_bytes)
        full_text = "\n\n".join(p["text"] for p in pages)
        if not full_text.strip():
            raise ValueError("No extractable text was found in the uploaded document")

        # 3. Create chunks. Index only after the relational record is durable.
        chunks = chunk_pages(
            pages=pages,
            contract_id=contract_id,
            supplier_id=supplier_id,
            document_name=filename,
        )
        supplier_name = supplier.supplier_name if supplier else ""

        extracted = await extract_contract_terms(full_text, supplier_name)

        # 4. Save Contract Record to PostgreSQL
        contract = Contract(
            contract_id=contract_id,
            supplier_id=supplier_id,
            contract_title=extracted.get("contract_title", filename),
            contract_type=extracted.get("contract_type", "Standard Supply Contract"),
            customer_name=extracted.get("customer_name", "Enterprise Procurement Corp"),
            agreement_date=date.today(),
            effective_date=date.today(),
            expiry_date=date(date.today().year + extracted.get("term_years", 3), date.today().month, date.today().day),
            term_years=extracted.get("term_years", 3),
            renewal_type=extracted.get("renewal_type", "Mutual written consent"),
            termination_notice_months=extracted.get("termination_notice_months", 2),
            governing_law=extracted.get("governing_law", "Standard jurisdiction"),
            contract_status="active",
            document_path=save_path,
            document_data=file_bytes,
            document_filename=filename,
            document_hash=doc_hash,
            extraction_status="completed",
        )
        db.add(contract)
        await db.flush()

        # 5. Save Terms
        terms = ContractTerms(
            contract_id=contract.contract_id,
            payment_on_order_pct=Decimal(str(extracted.get("payment_on_order_pct", 15.0))),
            payment_before_shipment_pct=Decimal(str(extracted.get("payment_before_shipment_pct", 85.0))),
            payment_terms_desc=extracted.get("payment_terms_desc", "Net 30 days"),
            lead_time_days=extracted.get("lead_time_days", 14),
            minimum_order_quantity=extracted.get("minimum_order_quantity", 50),
            warranty_months=str(extracted.get("warranty_months", "24 months")),
            penalty_for_delay=str(extracted.get("penalty_for_delay", "1% per week, max 10%")),
            defect_notification_days=extracted.get("defect_notification_days", 30),
            shipping_term=extracted.get("shipping_term", "FOB"),
        )
        db.add(terms)

        # 6. Ingestion Log and then vector indexing.
        duration = round(Decimal(str(time.time() - start_time)), 2)
        log = DocumentIngestionLog(
            contract_id=contract.contract_id,
            document_name=filename,
            status="completed",
            step="indexed",
            chunks_indexed=len(chunks),
            fields_extracted=len(extracted),
            processing_time_seconds=duration,
            completed_at=datetime.now(),
        )
        db.add(log)
        await db.commit()
        try:
            indexed_count = vector_store.upsert_chunks(chunks)
        except Exception:
            # Preserve the contract but expose a truthful retryable state.
            log.status = "failed"
            log.step = "vector_indexing"
            await db.commit()
            raise

        log.chunks_indexed = indexed_count
        await db.commit()

        return {
            "status": "success",
            "contract_id": contract.contract_id,
            "document_name": filename,
            "chunks_indexed": indexed_count,
            "fields_extracted": len(extracted),
            "processing_time_seconds": float(duration),
            "extracted_terms": extracted,
        }


ingestion_service = IngestionService()
