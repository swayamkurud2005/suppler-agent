"""
Full document ingestion pipeline:
File storage -> SHA-256 deduplication -> Parsing -> Chunking -> Vector Indexing ->
Structured LLM Extraction -> Database persistence.
"""

import os
import time
from datetime import datetime
from decimal import Decimal
import uuid
import logging
from pathlib import PurePosixPath

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
        filename = PurePosixPath((filename or "").replace("\\", "/")).name
        if PurePosixPath(filename).suffix.casefold() not in {".pdf", ".docx", ".doc", ".txt"}:
            raise ValueError("Unsupported contract file type.")
        if not file_bytes:
            raise ValueError("The uploaded contract file is empty.")
        if len(file_bytes) > settings.max_upload_bytes:
            raise ValueError("The uploaded contract file exceeds the configured size limit.")

        start_time = time.time()
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

        # 1. Compute Hash and Check Duplication
        doc_hash = calculate_file_hash(file_bytes)
        existing_stmt = select(Contract).where(Contract.document_hash == doc_hash)
        existing_contract = (await db.execute(existing_stmt)).scalars().first()

        contract_id = f"CTR-{uuid.uuid4().hex[:8].upper()}"
        save_path = os.path.join(settings.UPLOAD_DIR, f"{contract_id}_{filename}")
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        # 2. Parse Pages
        pages = parse_document(filename, file_bytes)
        full_text = "\n\n".join(p["text"] for p in pages)

        # 3. Create Chunks and Index in Vector Store
        chunks = chunk_pages(
            pages=pages,
            contract_id=contract_id,
            supplier_id=supplier_id,
            document_name=filename,
        )
        vector_store.upsert_chunks(chunks)

        # 4. Extract Structured Terms via LLM/Regex
        supplier_stmt = select(Supplier).where(Supplier.supplier_id == supplier_id)
        supplier = (await db.execute(supplier_stmt)).scalars().first()
        supplier_name = supplier.supplier_name if supplier else ""

        extracted = await extract_contract_terms(full_text, supplier_name)

        # 5. Save Contract Record to PostgreSQL
        contract = Contract(
            contract_id=contract_id,
            supplier_id=supplier_id,
            contract_title=extracted.get("contract_title", filename),
            contract_type=extracted.get("contract_type"),
            customer_name=extracted.get("customer_name"),
            agreement_date=extracted.get("agreement_date"),
            effective_date=extracted.get("effective_date"),
            expiry_date=extracted.get("expiry_date"),
            term_years=extracted.get("term_years"),
            renewal_type=extracted.get("renewal_type"),
            termination_notice_months=extracted.get("termination_notice_months"),
            governing_law=extracted.get("governing_law"),
            contract_status="unknown",
            document_path=save_path,
            document_hash=doc_hash,
            extraction_status="completed",
        )
        db.add(contract)
        await db.flush()

        # 6. Save Terms
        terms = ContractTerms(
            contract_id=contract.contract_id,
            payment_on_order_pct=Decimal(str(extracted["payment_on_order_pct"])) if extracted.get("payment_on_order_pct") is not None else None,
            payment_before_shipment_pct=Decimal(str(extracted["payment_before_shipment_pct"])) if extracted.get("payment_before_shipment_pct") is not None else None,
            payment_terms_desc=extracted.get("payment_terms_desc"),
            lead_time_days=extracted.get("lead_time_days"),
            minimum_order_quantity=extracted.get("minimum_order_quantity"),
            warranty_months=str(extracted["warranty_months"]) if extracted.get("warranty_months") is not None else None,
            penalty_for_delay=extracted.get("penalty_for_delay"),
            defect_notification_days=extracted.get("defect_notification_days"),
            shipping_term=extracted.get("shipping_term"),
        )
        db.add(terms)

        # 7. Ingestion Log
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

        return {
            "status": "success",
            "contract_id": contract.contract_id,
            "document_name": filename,
            "chunks_indexed": len(chunks),
            "fields_extracted": len(extracted),
            "processing_time_seconds": float(duration),
            "extracted_terms": extracted,
        }


ingestion_service = IngestionService()
