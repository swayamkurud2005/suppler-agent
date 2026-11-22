"""Local database smoke tests for durable evaluation history."""

import pytest
from fastapi import BackgroundTasks
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.endpoints import evaluations
from app.models.models import EvaluationRecord, EvaluationRun


@pytest.mark.asyncio
async def test_failed_evaluation_run_and_records_survive_session_boundaries():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(EvaluationRun.__table__.create)
            await connection.run_sync(EvaluationRecord.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async with sessions() as session:
            session.add(EvaluationRun(
                run_id="persistence-smoke",
                status="failed",
                error_message="Test failure remains queryable.",
                record_count=0,
            ))
            await session.commit()

        async with sessions() as session:
            run = await session.get(EvaluationRun, "persistence-smoke")
            records = (await session.scalars(
                select(EvaluationRecord).where(EvaluationRecord.run_id == "persistence-smoke")
            )).all()
            assert run is not None
            assert run.status == "failed"
            assert run.error_message == "Test failure remains queryable."
            assert records == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_evaluation_post_and_get_use_persistent_run_rows(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(EvaluationRun.__table__.create)
            await connection.run_sync(EvaluationRecord.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(evaluations.database, "ensure_evaluation_database", _noop_async)
        monkeypatch.setattr(evaluations.settings, "DEBUG", True)
        monkeypatch.setattr(evaluations.settings, "GROQ_API_KEY", "test-key")

        async with sessions() as session:
            response = await evaluations.start_evaluation(
                evaluations.EvaluationStartRequest(allow_external_calls=True),
                BackgroundTasks(),
                session,
            )
            run_id = response["run_id"]

        async with sessions() as session:
            fetched = await evaluations.get_evaluation_run(run_id, session)
            records = await evaluations.get_evaluation_records(run_id, offset=0, limit=25, db=session)
            assert fetched["data"]["status"] == "queued"
            assert records == {"data": [], "offset": 0, "limit": 25, "total": 0}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_run_recovery_preserves_run_and_evaluation_records():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(EvaluationRun.__table__.create)
            await connection.run_sync(EvaluationRecord.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        async with sessions() as session:
            stale = EvaluationRun(
                run_id="stale-running",
                status="running",
                record_count=1,
                created_at=now - timedelta(hours=2),
                started_at=now - timedelta(hours=2),
            )
            session.add(stale)
            session.add(EvaluationRecord(
                record_id="retained-record",
                run_id="stale-running",
                question_id="question-1",
                status="scored",
                metrics={"faithfulness": {"score": 0.7}},
                result={"metrics": {"faithfulness": {"score": 0.7}}},
            ))
            session.add(EvaluationRun(
                run_id="recent-running",
                status="running",
                record_count=0,
                created_at=now,
                started_at=now,
            ))
            await session.commit()

        async with sessions() as session:
            recovered = await evaluations._recover_stale_runs(session)
            assert recovered == 1

        async with sessions() as session:
            stale = await session.get(EvaluationRun, "stale-running")
            recent = await session.get(EvaluationRun, "recent-running")
            records = (await session.scalars(
                select(EvaluationRecord).where(EvaluationRecord.run_id == "stale-running")
            )).all()
            assert stale.status == "failed"
            assert "worker" in stale.error_message.lower()
            assert stale.completed_at is not None
            assert recent.status == "running"
            assert len(records) == 1
            assert records[0].result["metrics"]["faithfulness"]["score"] == 0.7
    finally:
        await engine.dispose()


async def _noop_async():
    return None
