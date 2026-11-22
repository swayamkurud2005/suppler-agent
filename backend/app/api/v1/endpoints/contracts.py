"""
Contracts API endpoints.
Includes listing all contracts with supplier info, downloading contract documents,
and evidence retrieval.
"""

import io
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.config import settings
from app.models.models import Contract, ContractTerms, Supplier
from app.schemas.schemas import APIResponse
from app.services.hybrid_retriever import hybrid_retriever

router = APIRouter()


def _document_payload(contract: Contract) -> list[dict]:
    """Expose document download metadata for a contract."""
    has_db_data = contract.document_data is not None and len(contract.document_data) > 0
    has_disk_file = contract.document_path and Path(contract.document_path).is_file()

    if not has_db_data and not has_disk_file:
        return []

    filename = contract.document_filename or (
        Path(contract.document_path).name if contract.document_path else "contract.pdf"
    )
    return [{
        "id": contract.contract_id,
        "name": filename,
        "type": "contract",
        "uploadDate": contract.created_at.strftime("%Y-%m-%d") if contract.created_at else None,
        "downloadUrl": f"/api/contracts/{contract.contract_id}/download",
        "hasCloudCopy": has_db_data,
    }]


@router.get("", response_model=APIResponse)
async def list_contracts(db: AsyncSession = Depends(get_db)):
    """List all contracts with supplier information and download availability."""
    stmt = (
        select(Contract)
        .options(selectinload(Contract.terms), selectinload(Contract.supplier))
    )
    result = await db.execute(stmt)
    contracts = result.scalars().all()

    data = []
    for c in contracts:
        t = c.terms
        sup = c.supplier
        docs = _document_payload(c)
        data.append({
            "id": c.contract_id,
            "supplierId": c.supplier_id,
            "supplierName": sup.supplier_name if sup else "Unknown Supplier",
            "supplierStatus": sup.status if sup else None,
            "supplierCategory": sup.category if sup else None,
            "status": c.contract_status,
            "startDate": c.effective_date.isoformat() if c.effective_date else None,
            "expiryDate": c.expiry_date.isoformat() if c.expiry_date else None,
            "paymentTerms": t.payment_terms_desc if t else None,
            "leadTimeDays": t.lead_time_days if t else None,
            "warrantyMonths": t.warranty_months if t else None,
            "penaltyForDelay": t.penalty_for_delay if t else None,
            "shippingTerm": t.shipping_term if t else None,
            "documents": docs,
            "hasDownload": len(docs) > 0,
            "contractTitle": c.contract_title,
            "contractType": c.contract_type,
            "customerName": c.customer_name,
            "renewalType": c.renewal_type,
            "termYears": c.term_years,
            "governingLaw": c.governing_law,
            "createdAt": c.created_at.isoformat() if c.created_at else None,
        })

    return APIResponse(status="success", data=data)


@router.get("/suppliers/{supplier_id}/contract", response_model=APIResponse)
async def get_contract_by_supplier(supplier_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Contract)
        .options(selectinload(Contract.terms), selectinload(Contract.supplier))
        .where(Contract.supplier_id == supplier_id)
        .order_by(Contract.created_at.desc())
    )
    result = await db.execute(stmt)
    c = result.scalars().first()

    if not c:
        return APIResponse(status="error", message="No contract found for supplier")

    t = c.terms
    sup = c.supplier
    docs = _document_payload(c)
    data = {
        "id": c.contract_id,
        "supplierId": c.supplier_id,
        "supplierName": sup.supplier_name if sup else "Unknown",
        "status": c.contract_status,
        "startDate": c.effective_date.isoformat() if c.effective_date else None,
        "expiryDate": c.expiry_date.isoformat() if c.expiry_date else None,
        "paymentTerms": t.payment_terms_desc if t else None,
        "leadTimeDays": t.lead_time_days if t else None,
        "warrantyMonths": t.warranty_months if t else None,
        "penaltyForDelay": t.penalty_for_delay if t else None,
        "documents": docs,
        "hasDownload": len(docs) > 0,
        "contractTitle": c.contract_title,
        "contractType": c.contract_type,
        "customerName": c.customer_name,
        "renewalType": c.renewal_type,
    }
    return APIResponse(status="success", data=data)


@router.get("/{contract_id}/download")
async def download_contract(contract_id: str, db: AsyncSession = Depends(get_db)):
    """Download a contract document. Serves from cloud DB (document_data) first,
    falls back to local disk (document_path)."""
    contract = (
        await db.execute(select(Contract).where(Contract.contract_id == contract_id))
    ).scalars().first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    filename = contract.document_filename or "contract.pdf"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    media_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "txt": "text/plain",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    # Priority 1: Serve from cloud database (document_data column)
    if contract.document_data and len(contract.document_data) > 0:
        return StreamingResponse(
            io.BytesIO(contract.document_data),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Priority 2: Serve from local disk
    if contract.document_path:
        stored_path = Path(contract.document_path).resolve()
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        if upload_root in stored_path.parents and stored_path.is_file():
            return FileResponse(stored_path, filename=filename, media_type=media_type)

    raise HTTPException(
        status_code=404,
        detail="Contract document file is not available for download. "
               "The original file may not have been stored in the cloud database."
    )


@router.get("/suppliers/{supplier_id}/evidence", response_model=APIResponse)
async def get_supplier_evidence(
    supplier_id: str,
    field: Optional[str] = None,
    query: Optional[str] = None,
):
    """Fetch contract evidence chunks from Qdrant/hybrid retriever for a specific supplier."""
    search_q = query or field or "terms SLA penalty warranty delivery pricing"
    evidence = hybrid_retriever.retrieve(
        query=search_q,
        supplier_id=supplier_id,
        top_k=5,
    )
    if not evidence:
        evidence = hybrid_retriever.retrieve(
            query="contract agreement obligations",
            supplier_id=supplier_id,
            top_k=5,
        )
    return APIResponse(status="success", data=evidence)


@router.get("/{contract_id}/evidence", response_model=APIResponse)
async def get_contract_evidence(contract_id: str, query: str = "terms SLA penalty warranty"):
    """Fetch contract evidence chunks matching query."""
    evidence = hybrid_retriever.retrieve(query=query, top_k=5)
    return APIResponse(status="success", data=evidence)
