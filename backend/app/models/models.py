"""
SQLAlchemy ORM models for the Supplier 360 database.

All tables follow normalized relational design with proper constraints,
indexes, foreign keys, and timestamps. Supports both string IDs (e.g., 'SUP-001')
and standard UUID strings for seamless frontend compatibility.
"""

import uuid
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    String, Text, Integer, Numeric, Boolean, Date, DateTime,
    ForeignKey, Index, CheckConstraint, UniqueConstraint,
    func, JSON, LargeBinary,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


# ──────────────────────────────────────────────────────────────
# A. suppliers
# ──────────────────────────────────────────────────────────────
class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relationship_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    contracts: Mapped[list["Contract"]] = relationship(back_populates="supplier", lazy="selectin")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier", lazy="selectin")
    quality_records: Mapped[list["QualityRecord"]] = relationship(back_populates="supplier", lazy="selectin")

    __table_args__ = (
        Index("ix_suppliers_name", "supplier_name"),
        Index("ix_suppliers_status", "status"),
    )


# ──────────────────────────────────────────────────────────────
# B. contracts
# ──────────────────────────────────────────────────────────────
class Contract(Base):
    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    supplier_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("suppliers.supplier_id"), nullable=True
    )
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contract_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agreement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    term_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    renewal_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    renewal_term_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    termination_notice_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    governing_law: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )
    document_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    document_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extraction_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    supplier: Mapped["Supplier | None"] = relationship(back_populates="contracts")
    terms: Mapped["ContractTerms | None"] = relationship(
        back_populates="contract", uselist=False, lazy="selectin"
    )
    contract_products: Mapped[list["ContractProduct"]] = relationship(
        back_populates="contract", lazy="selectin"
    )
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="contract", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_contracts_supplier", "supplier_id"),
        Index("ix_contracts_status", "contract_status"),
        Index("ix_contracts_expiry", "expiry_date"),
        Index("ix_contracts_hash", "document_hash"),
    )


# ──────────────────────────────────────────────────────────────
# C. contract_terms
# ──────────────────────────────────────────────────────────────
class ContractTerms(Base):
    __tablename__ = "contract_terms"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    contract_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("contracts.contract_id"), unique=True, nullable=False
    )
    payment_on_order_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    payment_before_shipment_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    payment_terms_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_order_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warranty_months: Mapped[str | None] = mapped_column(String(100), nullable=True)
    penalty_for_delay: Mapped[str | None] = mapped_column(String(255), nullable=True)
    defect_notification_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    breach_cure_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping_term: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipping_cost_responsibility: Mapped[str | None] = mapped_column(String(100), nullable=True)
    arbitration_organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    arbitration_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    additional_terms: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    contract: Mapped["Contract"] = relationship(back_populates="terms")


# ──────────────────────────────────────────────────────────────
# D. products
# ──────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    package_size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    package_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        Index("ix_products_name", "product_name"),
        Index("ix_products_category", "category"),
    )


# ──────────────────────────────────────────────────────────────
# E. contract_products
# ──────────────────────────────────────────────────────────────
class ContractProduct(Base):
    __tablename__ = "contract_products"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    contract_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("contracts.contract_id"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("products.product_id"), nullable=False
    )
    minimum_annual_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contracted_unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    price_valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    contract: Mapped["Contract"] = relationship(back_populates="contract_products")
    product: Mapped["Product"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_contract_products_contract", "contract_id"),
        Index("ix_contract_products_product", "product_id"),
    )


# ──────────────────────────────────────────────────────────────
# F. purchase_orders
# ──────────────────────────────────────────────────────────────
class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    order_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    supplier_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("suppliers.supplier_id"), nullable=False
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("contracts.contract_id"), nullable=True
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_orders")
    contract: Mapped["Contract | None"] = relationship(back_populates="purchase_orders")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order", lazy="selectin"
    )
    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="order", lazy="selectin")

    __table_args__ = (
        Index("ix_po_supplier", "supplier_id"),
        Index("ix_po_contract", "contract_id"),
        Index("ix_po_date", "order_date"),
    )


# ──────────────────────────────────────────────────────────────
# G. purchase_order_items
# ──────────────────────────────────────────────────────────────
class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    order_item_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("purchase_orders.order_id"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("products.product_id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_poi_order", "order_id"),
    )


# ──────────────────────────────────────────────────────────────
# H. deliveries
# ──────────────────────────────────────────────────────────────
class Delivery(Base):
    __tablename__ = "deliveries"

    delivery_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("purchase_orders.order_id"), nullable=False
    )
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    order: Mapped["PurchaseOrder"] = relationship(back_populates="deliveries")

    __table_args__ = (
        Index("ix_delivery_order", "order_id"),
    )


# ──────────────────────────────────────────────────────────────
# I. quality_records
# ──────────────────────────────────────────────────────────────
class QualityRecord(Base):
    __tablename__ = "quality_records"

    quality_record_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    supplier_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("suppliers.supplier_id"), nullable=False
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("contracts.contract_id"), nullable=True
    )
    product_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("products.product_id"), nullable=True
    )
    inspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_inspected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_defective: Mapped[int | None] = mapped_column(Integer, nullable=True)
    defect_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supplier: Mapped["Supplier"] = relationship(back_populates="quality_records")

    __table_args__ = (
        Index("ix_qr_supplier", "supplier_id"),
    )


# ──────────────────────────────────────────────────────────────
# J. market_price_benchmarks
# ──────────────────────────────────────────────────────────────
class MarketPriceBenchmark(Base):
    __tablename__ = "market_price_benchmarks"

    benchmark_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    product_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("products.product_id"), nullable=False
    )
    benchmark_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    benchmark_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    product: Mapped["Product"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_mpb_product", "product_id"),
        Index("ix_mpb_date", "benchmark_date"),
    )


# ──────────────────────────────────────────────────────────────
# K. document_ingestion_log
# ──────────────────────────────────────────────────────────────
class DocumentIngestionLog(Base):
    __tablename__ = "document_ingestion_log"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    contract_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("contracts.contract_id"), nullable=False
    )
    document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="uploaded"
    )  # uploaded, processing, completed, partially_completed, failed
    step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_time_seconds: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_dil_contract", "contract_id"),
        Index("ix_dil_status", "status"),
    )


# ──────────────────────────────────────────────────────────────
# L. chat_sessions — persistent conversation history
# ──────────────────────────────────────────────────────────────
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    supplier_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="New Chat")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_chat_sessions_supplier", "supplier_id"),
        Index("ix_chat_sessions_updated", "updated_at"),
    )


# ──────────────────────────────────────────────────────────────
# M. chat_messages — individual messages within a session
# ──────────────────────────────────────────────────────────────
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_sessions.session_id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    key_findings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    suggested_actions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_session", "session_id"),
    )


# ──────────────────────────────────────────────────────────────
# N. price_research_runs — Market price benchmarking research runs
# ──────────────────────────────────────────────────────────────
class PriceResearchRun(Base):
    __tablename__ = "price_research_runs"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    supplier_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("suppliers.supplier_id"), nullable=False
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("contracts.contract_id"), nullable=True
    )
    material_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    technical_characteristics: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    contract_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    contract_unit: Mapped[str] = mapped_column(String(50), nullable=False, default="kg")
    contract_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    annual_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    packaging_details: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True, default="India")
    comparison_period: Mapped[str | None] = mapped_column(String(50), nullable=True, default="Current Quarter")

    # Benchmarks
    market_benchmark_median: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    market_min_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    market_max_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    market_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    potential_annual_difference: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # AI Insight
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_insight: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    observations: Mapped[list["MarketPriceObservation"]] = relationship(
        back_populates="research_run", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_prr_supplier", "supplier_id"),
        Index("ix_prr_contract", "contract_id"),
        Index("ix_prr_created", "created_at"),
    )


# ──────────────────────────────────────────────────────────────
# O. market_price_observations — Individual market observations
# ──────────────────────────────────────────────────────────────
class MarketPriceObservation(Base):
    __tablename__ = "market_price_observations"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid_str
    )
    research_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("price_research_runs.id"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    material_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    raw_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    raw_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    normalized_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    normalized_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    normalized_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_rate_applied: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    unit_conversion_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    price_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_conditions: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_inclusion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    match_classification: Mapped[str] = mapped_column(String(50), nullable=False, default="high")
    match_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_included_in_benchmark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    research_run: Mapped["PriceResearchRun"] = relationship(back_populates="observations")

    __table_args__ = (
        Index("ix_mpo_run", "research_run_id"),
        Index("ix_mpo_match", "match_classification"),
    )
