"""Development-only APIs for local RAGAS evaluation runs."""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[4]
PROJECT_ROOT = BACKEND_DIR.parent
RESULTS_DIR = BACKEND_DIR / "runtime" / "evaluations" / "results"
RUNNER = BACKEND_DIR / "scripts" / "run_ragas_evaluation.py"

router = APIRouter()
_jobs: dict[str, dict[str, Any]] = {}


class EvaluationStartRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100)
    allow_external_calls: bool = False


def _require_development_mode() -> None:
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")


def _validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise HTTPException(status_code=404, detail="Evaluation run not found")


def _read_summary(run_id: str) -> dict[str, Any] | None:
    path = RESULTS_DIR / run_id / "summary.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Return only stable, non-content metadata; never include answers or contexts.
    return {
        "run_id": run_id,
        "status": "completed",
        "created_at_utc": value.get("created_at_utc"),
        "record_count": value.get("record_count"),
        "record_status_counts": value.get("record_status_counts", {}),
        "metrics": value.get("metrics", {}),
        "evaluator": value.get("evaluator", {}),
    }


async def _execute_job(run_id: str, limit: int | None) -> None:
    job = _jobs[run_id]
    job["status"] = "running"
    command = [
        sys.executable,
        str(RUNNER),
        "--run-id",
        run_id,
        "--allow-external-calls",
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return_code = await process.wait()
        job["status"] = "completed" if return_code == 0 else "failed"
        if return_code != 0:
            job["error"] = "Evaluation process failed. Inspect local backend logs."
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = f"Evaluation process could not start ({type(exc).__name__})."


@router.post("/runs", status_code=202, dependencies=[Depends(_require_development_mode)])
async def start_evaluation(request: EvaluationStartRequest, background_tasks: BackgroundTasks):
    """Queue a run only after an explicit request acknowledges Groq data transfer."""
    if not request.allow_external_calls:
        raise HTTPException(
            status_code=400,
            detail="Set allow_external_calls=true to send prompts, answers, and retrieved excerpts to Groq.",
        )
    if not settings.GROQ_API_KEY.strip():
        raise HTTPException(status_code=503, detail="Groq evaluation credentials are not configured.")
    if not RUNNER.is_file():
        raise HTTPException(status_code=503, detail="Evaluation runner is unavailable.")
    if any(job["status"] in {"queued", "running"} for job in _jobs.values()):
        raise HTTPException(status_code=409, detail="An evaluation run is already in progress.")

    run_id = uuid4().hex
    _jobs[run_id] = {
        "run_id": run_id,
        "status": "queued",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    background_tasks.add_task(_execute_job, run_id, request.limit)
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs", dependencies=[Depends(_require_development_mode)])
async def list_evaluation_runs():
    summaries = []
    if RESULTS_DIR.is_dir():
        for child in RESULTS_DIR.iterdir():
            if child.is_dir() and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", child.name):
                summary = _read_summary(child.name)
                if summary:
                    summaries.append(summary)

    completed_ids = {item["run_id"] for item in summaries}
    for run_id, job in _jobs.items():
        if run_id not in completed_ids:
            summaries.append({
                "run_id": run_id,
                "status": job["status"],
                "created_at_utc": job["created_at_utc"],
                "error": job["error"],
            })
    summaries.sort(key=lambda item: item.get("created_at_utc") or "", reverse=True)
    return {"data": summaries}


@router.get("/runs/{run_id}", dependencies=[Depends(_require_development_mode)])
async def get_evaluation_run(run_id: str):
    _validate_run_id(run_id)
    summary = _read_summary(run_id)
    if summary:
        return {"data": summary}
    job = _jobs.get(run_id)
    if job:
        return {"data": dict(job)}
    raise HTTPException(status_code=404, detail="Evaluation run not found")


@router.get("/runs/{run_id}/records", dependencies=[Depends(_require_development_mode)])
async def get_evaluation_records(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
):
    _validate_run_id(run_id)
    path = RESULTS_DIR / run_id / "results.jsonl"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Evaluation records not found")

    records = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    records.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="Evaluation records could not be read")

    safe_fields = (
        "run_id", "question_id", "category", "difficulty", "source_document",
        "ground_truth_status", "request_id", "trace_id", "generation_mode",
        "model_name", "llm_calls", "retrieved_context_ids", "retrieved_document_ids",
        "metrics", "status", "skip_reason", "error_type",
    )
    page = [{key: row[key] for key in safe_fields if key in row} for row in records[offset:offset + limit]]
    return {"data": page, "offset": offset, "limit": limit, "total": len(records)}
