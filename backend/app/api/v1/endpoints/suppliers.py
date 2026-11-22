"""
Suppliers API endpoints.
Includes listing, filtering, detail retrieval, and new supplier creation.
"""

import os
import glob
import logging
from typing import Optional, List
from datetime import date, timedelta
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from app.core.config import settings
from app.core.database import get_db
from app.models.models import (Supplier, Contract, ContractTerms, ContractProduct,
    DocumentIngestionLog, PurchaseOrder, PurchaseOrderItem, Delivery, QualityRecord)
from app.schemas.schemas import APIResponse, SupplierResponse
from app.services.sql_retriever import sql_retriever
from app.services.vector_store import vector_store
from app.services.supplier_extractor import supplier_extractor
from app.services.ingestion import ingestion_service

logger = logging.getLogger("suppliers_api")

router = APIRouter()


class CreateSupplierRequest(BaseModel):
    name: str
    category: Optional[str] = "General Supplies"
    location: Optional[str] = ""
    country: Optional[str] = "India"
    contactPerson: Optional[str] = None
    contactEmail: Optional[str] = None
    contactPhone: Optional[str] = None
    relationshipYears: Optional[int] = 1
    riskScore: Optional[int] = 25
    status: Optional[str] = "active"
    documentToken: Optional[str] = None
    contractFileName: Optional[str] = None


class ExtractExistingDocumentRequest(BaseModel):
    document_name: Optional[str] = None
    contract_id: Optional[str] = None
    supplier_id: Optional[str] = None


@router.get("/available-documents", response_model=APIResponse)
async def list_available_documents(db: AsyncSession = Depends(get_db)):
    """
    List all previously uploaded or stored contract documents.
    Allows extracting supplier details from existing documents without re-uploading.
    """
    try:
        docs = await supplier_extractor.get_available_documents(db)
        return APIResponse(status="success", data=docs, message=f"Found {len(docs)} available documents")
    except Exception as e:
        logger.exception("Failed to fetch available documents")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-from-existing", response_model=APIResponse)
async def extract_supplier_from_existing(
    req: ExtractExistingDocumentRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Extract structured supplier details from an already-uploaded contract document.
    No re-upload needed: finds existing document by document_name, contract_id, or supplier_id.
    """
    try:
        res = await supplier_extractor.extract_from_existing_document(
            db=db,
            document_name=req.document_name,
            contract_id=req.contract_id,
            supplier_id=req.supplier_id,
        )
        return APIResponse(status="success", data=res, message="Details successfully extracted from existing document")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("Extraction from existing document failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@router.post("/extract-from-contract", response_model=APIResponse)
async def extract_supplier_from_contract(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract structured supplier details from an uploaded contract document.
    Uses hybrid RAG retrieval + LLM extraction with source citations and confidence scores.
    """
    try:
        content = await file.read()
        res = await supplier_extractor.extract_from_contract(
            filename=file.filename or "contract.pdf",
            file_bytes=content,
            db=db,
        )
        return APIResponse(status="success", data=res, message="Contract details successfully extracted")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("Contract extraction failed")
        raise HTTPException(status_code=500, detail=f"AI Contract extraction failed: {str(e)}")


@router.get("", response_model=APIResponse)
async def list_suppliers(
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Supplier)
    if status:
        stmt = stmt.where(Supplier.status == status)
    if category:
        stmt = stmt.where(Supplier.category == category)
    if search:
        s = f"%{search.lower()}%"
        stmt = stmt.where(
            (Supplier.supplier_name.ilike(s)) |
            (Supplier.category.ilike(s)) |
            (Supplier.location.ilike(s))
        )

    result = await db.execute(stmt)
    suppliers = result.scalars().all()

    data = []
    for s in suppliers:
        renewal_date = None
        if s.contracts:
            exp_dates = [c.expiry_date for c in s.contracts if c.expiry_date]
            if exp_dates:
                renewal_date = max(exp_dates).isoformat()

        last_order_date = None
        if s.purchase_orders:
            po_dates = [po.order_date for po in s.purchase_orders if po.order_date]
            if po_dates:
                last_order_date = max(po_dates).isoformat()

        data.append({
            "id": s.supplier_id,
            "name": s.supplier_name,
            "category": s.category,
            "location": s.location,
            "status": s.status,
            "relationshipYears": s.relationship_years or 1,
            "lastOrderDate": last_order_date,
            "renewalDate": renewal_date,
            "contactPerson": s.contact_person,
            "contactEmail": s.contact_email,
            "contactPhone": s.contact_phone,
            "riskScore": s.risk_score or 30,
        })
    return APIResponse(status="success", data=data)


@router.post("", response_model=APIResponse)
async def create_supplier(req: CreateSupplierRequest, db: AsyncSession = Depends(get_db)):
    """Create a new supplier in the database and optionally link an uploaded contract."""
    clean_name = req.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Supplier name is required")

    # Check for duplicate supplier name
    existing_stmt = select(Supplier).where(func.lower(Supplier.supplier_name) == func.lower(clean_name))
    existing_supplier = (await db.execute(existing_stmt)).scalars().first()
    if existing_supplier:
        raise HTTPException(
            status_code=409,
            detail=f"A supplier partner named '{clean_name}' is already registered (Supplier ID: {existing_supplier.supplier_id})."
        )

    # Auto-generate next sequential supplier ID
    stmt = select(Supplier.supplier_id)
    all_ids = (await db.execute(stmt)).scalars().all()
    max_num = 0
    for sid in all_ids:
        if sid.startswith("SUP-"):
            try:
                num = int(sid.split("-")[1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                pass
    next_id = f"SUP-{max_num + 1:03d}"

    new_supplier = Supplier(
        supplier_id=next_id,
        supplier_name=clean_name,
        category=req.category or "General Supplies",
        location=req.location or "India",
        country=req.country or "India",
        contact_person=req.contactPerson,
        contact_email=req.contactEmail,
        contact_phone=req.contactPhone,
        relationship_years=req.relationshipYears or 1,
        risk_score=req.riskScore or 25,
        status=req.status or "active",
    )
    db.add(new_supplier)
    await db.commit()
    await db.refresh(new_supplier)

    contract_info = None
    # If a contract document token was provided, finalize contract ingestion for this new supplier
    if req.documentToken:
        try:
            temp_pattern = os.path.join(settings.UPLOAD_DIR, f"{req.documentToken}_*")
            matching_files = glob.glob(temp_pattern)
            if matching_files:
                temp_file_path = matching_files[0]
                with open(temp_file_path, "rb") as f:
                    file_bytes = f.read()
                filename = req.contractFileName or os.path.basename(temp_file_path).split(f"{req.documentToken}_", 1)[-1]
                
                contract_res = await ingestion_service.ingest_contract(
                    db=db,
                    filename=filename,
                    file_bytes=file_bytes,
                    supplier_id=new_supplier.supplier_id,
                )
                contract_info = contract_res
                # Remove temporary upload file
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Contract linking after supplier creation had an issue: {e}")
            contract_info = {"status": "warning", "message": f"Supplier created, but contract indexing encountered: {str(e)}"}

    data = {
        "id": new_supplier.supplier_id,
        "name": new_supplier.supplier_name,
        "category": new_supplier.category,
        "location": new_supplier.location,
        "status": new_supplier.status,
        "relationshipYears": new_supplier.relationship_years,
        "lastOrderDate": None,
        "renewalDate": None,
        "contactPerson": new_supplier.contact_person,
        "contactEmail": new_supplier.contact_email,
        "contactPhone": new_supplier.contact_phone,
        "riskScore": new_supplier.risk_score,
        "contract": contract_info,
    }
    return APIResponse(status="success", data=data, message="Supplier created successfully")


@router.delete("/{supplier_id}", response_model=APIResponse)
async def delete_supplier(supplier_id: str, db: AsyncSession = Depends(get_db)):
    """Hard-delete a supplier only after explicitly removing its dependent data.

    This avoids orphaned RAG chunks and relies on a single transaction for the
    relational side. Associated PO/contract records are deliberately removed
    only after the user confirmed deletion in the UI.
    """
    supplier = (await db.execute(select(Supplier).where(Supplier.supplier_id == supplier_id))).scalars().first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    contract_ids = list((await db.execute(select(Contract.contract_id).where(Contract.supplier_id == supplier_id))).scalars())
    order_ids = list((await db.execute(select(PurchaseOrder.order_id).where(PurchaseOrder.supplier_id == supplier_id))).scalars())
    if order_ids:
        await db.execute(delete(Delivery).where(Delivery.order_id.in_(order_ids)))
        await db.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids)))
    await db.execute(delete(QualityRecord).where(QualityRecord.supplier_id == supplier_id))
    await db.execute(delete(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier_id))
    if contract_ids:
        await db.execute(delete(DocumentIngestionLog).where(DocumentIngestionLog.contract_id.in_(contract_ids)))
        await db.execute(delete(ContractTerms).where(ContractTerms.contract_id.in_(contract_ids)))
        await db.execute(delete(ContractProduct).where(ContractProduct.contract_id.in_(contract_ids)))
    await db.execute(delete(Contract).where(Contract.supplier_id == supplier_id))
    await db.delete(supplier)
    await db.commit()
    vector_store.delete_by_supplier(supplier_id)
    return APIResponse(status="success", data={"id": supplier_id}, message="Supplier and associated procurement data deleted")


@router.get("/categories", response_model=APIResponse)
async def get_categories(db: AsyncSession = Depends(get_db)):
    stmt = select(Supplier.category).distinct().where(Supplier.category.isnot(None))
    result = await db.execute(stmt)
    categories = [r[0] for r in result.all() if r[0]]
    return APIResponse(status="success", data=categories)


@router.get("/{supplier_id}", response_model=APIResponse)
async def get_supplier(supplier_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Supplier).where(Supplier.supplier_id == supplier_id)
    result = await db.execute(stmt)
    s = result.scalars().first()
    if not s:
        return APIResponse(status="error", message="Supplier not found", data=None)

    data = {
        "id": s.supplier_id,
        "name": s.supplier_name,
        "category": s.category,
        "location": s.location,
        "status": s.status,
        "relationshipYears": s.relationship_years,
        "lastOrderDate": None,
        "renewalDate": None,
        "contactPerson": s.contact_person,
        "contactEmail": s.contact_email,
        "contactPhone": s.contact_phone,
        "riskScore": s.risk_score or 30,
    }
    return APIResponse(status="success", data=data)


@router.get("/{supplier_id}/overview", response_model=APIResponse)
async def get_supplier_overview(supplier_id: str, db: AsyncSession = Depends(get_db)):
    summary = await sql_retriever.get_supplier_summary(db, supplier_id)
    if not summary:
        return APIResponse(status="error", message="Supplier not found")

    kpis = await sql_retriever.get_performance_kpis(db, supplier_id)
    contract = await sql_retriever.get_contract_details(db, supplier_id)

    overview = {
        "supplier": summary,
        "kpis": kpis,
        "contract": contract,
    }
    return APIResponse(status="success", data=overview)
