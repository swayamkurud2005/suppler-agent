"""Persist RAGAS evaluation runs and per-record scores.

Revision ID: c31f4b7a92de
Revises: a9c2d76f1340
"""
from alembic import op
import sqlalchemy as sa

revision = "c31f4b7a92de"
down_revision = "a9c2d76f1340"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names(schema="public"))
    if "evaluation_runs" not in tables:
        op.create_table(
            "evaluation_runs",
            sa.Column("run_id", sa.String(64), primary_key=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=True),
        )
        op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])

    if "evaluation_records" not in tables:
        op.create_table(
            "evaluation_records",
            sa.Column("record_id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(64), sa.ForeignKey("evaluation_runs.run_id", ondelete="CASCADE"), nullable=False),
            sa.Column("question_id", sa.String(255), nullable=True),
            sa.Column("category", sa.String(255), nullable=True),
            sa.Column("difficulty", sa.String(100), nullable=True),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_evaluation_records_run_id", "evaluation_records", ["run_id"])


def downgrade() -> None:
    # These tables contain user evaluation history; intentionally retain them on downgrade.
    pass
