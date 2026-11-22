"""Add compatible metadata for market price benchmarks.

Revision ID: a9c2d76f1340
Revises: bf11d01aaa15
"""
from alembic import op
import sqlalchemy as sa

revision = "a9c2d76f1340"
down_revision = "bf11d01aaa15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("market_price_benchmarks")}
    columns = [
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("benchmark_type", sa.String(50), nullable=False, server_default="supplier_quotation"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="unverified"),
        sa.Column("metal_symbol", sa.String(20), nullable=True),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column("market_price_benchmarks", column)


def downgrade() -> None:
    op.drop_column("market_price_benchmarks", "metal_symbol")
    op.drop_column("market_price_benchmarks", "verification_status")
    op.drop_column("market_price_benchmarks", "match_confidence")
    op.drop_column("market_price_benchmarks", "retrieved_at")
    op.drop_column("market_price_benchmarks", "benchmark_type")
    op.drop_column("market_price_benchmarks", "unit")
