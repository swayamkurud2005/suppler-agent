"""Dashboard data derived exclusively from persisted procurement records."""
from collections import defaultdict
from datetime import date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.models import Supplier, Contract, PurchaseOrder, Delivery, QualityRecord
from app.schemas.schemas import APIResponse

router = APIRouter()

@router.get("/metrics", response_model=APIResponse)
async def get_dashboard_metrics(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(Supplier.supplier_id)))).scalar() or 0
    active = (await db.execute(select(func.count(Supplier.supplier_id)).where(Supplier.status == "active"))).scalar() or 0
    active_contracts = (await db.execute(select(func.count(Contract.contract_id)).where(Contract.contract_status == "active"))).scalar() or 0
    cutoff = date.today() + timedelta(days=90)
    expiring = (await db.execute(select(func.count(Contract.contract_id)).where(Contract.expiry_date.is_not(None), Contract.expiry_date <= cutoff))).scalar() or 0
    attention = (await db.execute(select(func.count(Supplier.supplier_id)).where((Supplier.status == "under_review") | (Supplier.risk_score >= 60)))).scalar() or 0
    _, spend = (await db.execute(select(func.count(PurchaseOrder.order_id), func.coalesce(func.sum(PurchaseOrder.total_amount), 0)))).one()
    delivered = [d for d in (await db.execute(select(Delivery))).scalars().all() if d.delivery_status == "delivered" and d.actual_delivery_date and d.expected_delivery_date]
    otd = round(sum(d.actual_delivery_date <= d.expected_delivery_date for d in delivered) / len(delivered) * 100, 1) if delivered else 0.0
    inspected, defective = (await db.execute(select(func.coalesce(func.sum(QualityRecord.quantity_inspected), 0), func.coalesce(func.sum(QualityRecord.quantity_defective), 0)))).one()
    defect = round(float(defective) / float(inspected) * 100, 2) if inspected else 0.0
    return APIResponse(data={"totalSuppliers": total, "activeSuppliers": active, "contractsExpiringSoon": expiring, "suppliersRequiringAttention": attention, "avgOnTimeDelivery": otd, "avgDefectRate": defect, "totalSpendYTD": float(spend or 0), "activeContracts": active_contracts})

@router.get("/charts", response_model=APIResponse)
async def get_dashboard_charts(db: AsyncSession = Depends(get_db)):
    suppliers = (await db.execute(select(Supplier))).scalars().all()
    supplier_by_id = {s.supplier_id: s for s in suppliers}
    orders = (await db.execute(select(PurchaseOrder))).scalars().all()
    deliveries = (await db.execute(select(Delivery).join(PurchaseOrder))).scalars().all()
    quality = (await db.execute(select(QualityRecord))).scalars().all()
    contracts = (await db.execute(select(Contract))).scalars().all()
    delivery_stats, quality_stats = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for d in deliveries:
        stats = delivery_stats[d.order.supplier_id]; stats[1] += 1
        if d.actual_delivery_date and d.expected_delivery_date and d.actual_delivery_date <= d.expected_delivery_date: stats[0] += 1
    for q in quality:
        stats = quality_stats[q.supplier_id]; stats[0] += q.quantity_inspected or 0; stats[1] += q.quantity_defective or 0
    performance, attention = [], []
    for s in suppliers:
        ontime, total = delivery_stats[s.supplier_id]; inspected, defective = quality_stats[s.supplier_id]
        delivery = round(ontime / total * 100, 1) if total else 0.0
        acceptance = round((1 - defective / inspected) * 100, 1) if inspected else 0.0
        performance.append({"name": s.supplier_name, "supplierId": s.supplier_id, "delivery": delivery, "quality": acceptance, "score": round((delivery + acceptance) / 2, 1) if total or inspected else 0.0})
        if s.status == "under_review" or (s.risk_score or 0) >= 60:
            attention.append({"supplier": s.supplier_name, "supplierId": s.supplier_id, "issue": "Supplier is under review" if s.status == "under_review" else f"Risk score is {s.risk_score}/100", "severity": "error" if s.status == "under_review" else "warning"})
    timeline = []
    for c in contracts:
        if c.expiry_date:
            days = (c.expiry_date - date.today()).days; s = supplier_by_id.get(c.supplier_id)
            timeline.append({"supplier": s.supplier_name if s else c.supplier_id, "supplierId": c.supplier_id, "daysRemaining": days, "status": c.contract_status})
            if days <= 90: attention.append({"supplier": s.supplier_name if s else c.supplier_id, "supplierId": c.supplier_id, "issue": f"Contract expires in {days} days", "severity": "error" if days < 0 else "warning"})
    monthly = defaultdict(float)
    for po in orders:
        if po.order_date and po.order_date.year == date.today().year: monthly[po.order_date.strftime("%b")] += float(po.total_amount or 0)
    return APIResponse(data={"attentionItems": attention, "spendTrend": [{"month": k, "spend": round(v, 2)} for k, v in monthly.items()], "supplierPerformance": performance, "contractTimeline": timeline})
