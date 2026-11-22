"""Development-only APIs for durable RAGAS evaluation runs."""

import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import database
from app.core.config import settings
from app.core.database import get_db
from app.models.models import EvaluationRecord, EvaluationRun

BACKEND_DIR = Path(__file__).resolve().parents[4]
PROJECT_ROOT = BACKEND_DIR.parent
RUNNER = BACKEND_DIR / "scripts" / "run_ragas_evaluation.py"
WORKER_TIMEOUT_SECONDS = 1800
STALE_RUN_GRACE_SECONDS = 120

router = APIRouter()
logger = logging.getLogger("supplier360.evaluation")


class EvaluationStartRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100)
    allow_external_calls: bool = False


def _require_development_mode() -> None:
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")


def _validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise HTTPException(status_code=404, detail="Evaluation run not found")


async def _require_persistent_database() -> None:
    try:
        await database.ensure_evaluation_database()
    except Exception as exc:
        # Avoid returning connection details or credentials to API callers.
        raise HTTPException(
            status_code=503,
            detail=f"Evaluation persistence database is unavailable ({type(exc).__name__}).",
        ) from exc


async def _recover_stale_runs(db: AsyncSession) -> int:
    """Close runs whose worker outlived its owning API/background-task process.

    This only changes stale run status/error metadata. It never removes run
    rows or any per-question history. The grace period exceeds the worker's
    explicit timeout so a healthy worker gets time to persist its terminal state.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=WORKER_TIMEOUT_SECONDS + STALE_RUN_GRACE_SECONDS)
    stale = (await db.scalars(
        select(EvaluationRun)
        .where(
            EvaluationRun.status.in_(["queued", "running"]),
            func.coalesce(EvaluationRun.started_at, EvaluationRun.created_at) < cutoff,
        )
        .with_for_update()
    )).all()
    for run in stale:
        run.status = "failed"
        run.error_message = (
            "Evaluation worker did not complete within the worker timeout. "
            "The run was recovered after its API worker disappeared; existing records were retained."
        )
        run.completed_at = now
    if stale:
        await db.commit()
        logger.warning("Recovered %s stale evaluation run(s).", len(stale))
    return len(stale)


async def _execute_job(run_id: str, limit: int | None) -> None:
    """Run the existing evaluator and persist its terminal state in the same DB."""
    async with database.async_session_factory() as db:
        run = await db.get(EvaluationRun, run_id)
        if not run:
            return
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

    command = [sys.executable, str(RUNNER), "--run-id", run_id, "--allow-external-calls"]
    if limit is not None:
        command.extend(["--limit", str(limit)])

    error_message = None
    try:
        await database.ensure_evaluation_database()
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=WORKER_TIMEOUT_SECONDS
        )
        return_code = process.returncode
        if return_code != 0:
            safe_lines = [line.strip() for line in stderr.decode("utf-8", errors="replace").splitlines() if line.strip()]
            error_message = safe_lines[-1][:500] if safe_lines else "Evaluation worker failed. Check backend logs and configuration."
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        error_message = f"Evaluation worker timed out after {WORKER_TIMEOUT_SECONDS} seconds."
    except Exception as exc:
        error_message = f"Evaluation worker failed ({type(exc).__name__})."

    try:
        await database.ensure_evaluation_database()
        async with database.async_session_factory() as db:
            run = await db.get(EvaluationRun, run_id)
            if run:
                # The runner sets completed itself after committing records. A
                # nonzero exit always wins and remains queryable as a failure.
                if error_message:
                    run.status = "failed"
                    run.error_message = error_message
                    run.completed_at = datetime.now(timezone.utc)
                elif run.status not in {"completed", "failed"}:
                    run.status = "failed"
                    run.error_message = "Evaluation worker exited without a terminal status."
                    run.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception:
        # The original run row remains in its last durable state; log generic
        # failure context without leaking connection strings.
        logger.exception("Could not persist evaluation worker terminal state")


@router.post("/runs", status_code=202, dependencies=[Depends(_require_development_mode)])
async def start_evaluation(
    request: EvaluationStartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Queue a run only after explicit consent to external Groq calls."""
    if not request.allow_external_calls:
        raise HTTPException(
            status_code=400,
            detail="Set allow_external_calls=true to send prompts, answers, and retrieved excerpts to Groq.",
        )
    if not settings.GROQ_API_KEY.strip():
        raise HTTPException(status_code=503, detail="Groq evaluation credentials are not configured.")
    if not RUNNER.is_file():
        raise HTTPException(status_code=503, detail="Evaluation runner is unavailable.")
    await _require_persistent_database()
    await _recover_stale_runs(db)
    active = await db.scalar(select(EvaluationRun.run_id).where(EvaluationRun.status.in_(["queued", "running"])).limit(1))
    if active:
        raise HTTPException(status_code=409, detail="An evaluation run is already in progress.")

    run_id = uuid4().hex
    run = EvaluationRun(run_id=run_id, status="queued", record_count=0)
    db.add(run)
    await db.commit()  # Ensure durable before a background task can start.
    background_tasks.add_task(_execute_job, run_id, request.limit)
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs", dependencies=[Depends(_require_development_mode)])
async def list_evaluation_runs(db: AsyncSession = Depends(get_db)):
    await _require_persistent_database()
    await _recover_stale_runs(db)
    rows = (await db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100))).all()
    return {"data": [_run_json(run) for run in rows]}


def _run_json(run: EvaluationRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "status": run.status,
        "created_at_utc": run.created_at.isoformat() if run.created_at else None,
        "started_at_utc": run.started_at.isoformat() if run.started_at else None,
        "completed_at_utc": run.completed_at.isoformat() if run.completed_at else None,
        "record_count": run.record_count,
        "record_status_counts": (run.summary or {}).get("record_status_counts", {}),
        "error": run.error_message,
        "metrics": (run.summary or {}).get("metrics", {}),
        "evaluator": (run.summary or {}).get("evaluator", {}),
    }


@router.get("/runs/{run_id}", dependencies=[Depends(_require_development_mode)])
async def get_evaluation_run(run_id: str, db: AsyncSession = Depends(get_db)):
    _validate_run_id(run_id)
    await _require_persistent_database()
    await _recover_stale_runs(db)
    run = await db.get(EvaluationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return {"data": _run_json(run)}


@router.get("/runs/{run_id}/records", dependencies=[Depends(_require_development_mode)])
async def get_evaluation_records(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    _validate_run_id(run_id)
    await _require_persistent_database()
    await _recover_stale_runs(db)
    if not await db.get(EvaluationRun, run_id):
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    query = select(EvaluationRecord).where(EvaluationRecord.run_id == run_id).order_by(EvaluationRecord.created_at, EvaluationRecord.record_id)
    total = await db.scalar(
        select(func.count()).select_from(EvaluationRecord).where(EvaluationRecord.run_id == run_id)
    )
    records = (await db.scalars(query.offset(offset).limit(limit))).all()
    return {"data": [record.result for record in records], "offset": offset, "limit": limit, "total": total}
