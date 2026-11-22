"""Run the versioned contract QA dataset through Supplier360 and score with RAGAS.

This command intentionally requires --allow-external-calls because the existing
workflow and the RAGAS judge send prompts, answers, and retrieved excerpts to Groq.
Results (including answer/context evidence) are written only to ignored runtime files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import re
import sys
import subprocess
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_DIR / "runtime" / "evaluations" / "datasets" / "contract_qa_v1.jsonl"
RESULTS_DIR = BACKEND_DIR / "runtime" / "evaluations" / "results"

sys.path.insert(0, str(BACKEND_DIR))

logger = logging.getLogger("supplier360.evaluation")
METRIC_NAMES = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)


def load_dataset(dataset_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with dataset_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on dataset line {line_number}.") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Dataset line {line_number} must be a JSON object.")
            records.append(record)
    if not records:
        raise ValueError(f"No evaluation records found in {dataset_path}.")
    return records


def unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "score": None, "reason": reason}


def error_result(exc: Exception) -> dict[str, Any]:
    # Do not serialize exception text: providers can include request data in it.
    return {"status": "error", "score": None, "error_type": type(exc).__name__}


async def resolve_supplier_id(db, record: dict[str, Any], contract_model) -> tuple[str | None, str | None]:
    """Resolve a real supplier scope from explicit indexed IDs or source hash."""
    explicit = str(record.get("supplier_id") or "").strip()
    source_ids_raw = record.get("source_ids") or []
    if not isinstance(source_ids_raw, list):
        return None, "source_ids must be a list of confirmed indexed IDs."
    source_ids = [str(value).strip() for value in source_ids_raw if str(value).strip()]

    if explicit:
        return explicit, None

    if source_ids:
        rows = await db.execute(
            select(contract_model.supplier_id).where(contract_model.contract_id.in_(source_ids))
        )
    else:
        source_hash = str(record.get("source_sha256") or "").strip().lower()
        if not source_hash:
            return None, "No supplier_id, source_ids, or source_sha256 is available."
        rows = await db.execute(
            select(contract_model.supplier_id).where(func.lower(contract_model.document_hash) == source_hash)
        )

    supplier_ids = {supplier_id for supplier_id in rows.scalars().all() if supplier_id}
    if len(supplier_ids) == 1:
        return next(iter(supplier_ids)), None
    if not supplier_ids:
        return None, "No indexed contract maps to this source record."
    return None, "Source record maps to multiple suppliers; add confirmed source_ids to the dataset."


def build_metrics(groq_key: str, model_name: str, embedding_model_name: str):
    """Construct the four RAGAS metrics using the project's Groq/local embedding setup."""
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_groq import ChatGroq
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextRecall,
            ResponseRelevancy,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Evaluation dependencies are missing. Install backend/requirements-evaluation.txt."
        ) from exc

    judge_llm = LangchainLLMWrapper(
        ChatGroq(api_key=groq_key, model=model_name, temperature=0)
    )
    metrics = {
        "faithfulness": Faithfulness(llm=judge_llm),
        "answer_relevancy": None,
        "context_precision": LLMContextPrecisionWithReference(llm=judge_llm),
        "context_recall": LLMContextRecall(llm=judge_llm),
    }
    embedding_error = None
    try:
        embedding_model = HuggingFaceEmbeddings(
            model_name=embedding_model_name,
            model_kwargs={"local_files_only": True},
            encode_kwargs={"normalize_embeddings": True},
        )
        judge_embeddings = LangchainEmbeddingsWrapper(embedding_model)
        metrics["answer_relevancy"] = ResponseRelevancy(llm=judge_llm, embeddings=judge_embeddings)
    except Exception as exc:
        embedding_error = type(exc).__name__
    return metrics, embedding_error


async def score_case(metrics: dict[str, Any], record: dict[str, Any], answer: str,
                     contexts: list[str], embedding_error: str | None = None) -> dict[str, Any]:
    from ragas.dataset_schema import SingleTurnSample

    question = str(record.get("question") or "")
    has_reference = (
        record.get("ground_truth_status") == "verified"
        and bool(str(record.get("reference_answer") or "").strip())
    )
    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
        reference=str(record.get("reference_answer") or "") if has_reference else None,
    )
    output: dict[str, Any] = {}

    for name in METRIC_NAMES:
        if not answer.strip():
            output[name] = unavailable("The workflow returned no answer.")
            continue
        if name == "faithfulness" and not contexts:
            output[name] = unavailable("No retrieved contexts were returned.")
            continue
        if name == "answer_relevancy" and embedding_error:
            output[name] = unavailable("Local evaluator embeddings are unavailable.")
            continue
        if name in {"context_precision", "context_recall"} and not has_reference:
            output[name] = unavailable("A verified reference answer is required.")
            continue
        if name in {"context_precision", "context_recall"} and not contexts:
            output[name] = unavailable("No retrieved contexts were returned.")
            continue

        try:
            value = await metrics[name].single_turn_ascore(sample)
            value = getattr(value, "value", value)
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("RAGAS returned a non-finite score")
            output[name] = {"status": "scored", "score": numeric}
        except Exception as exc:  # keep one metric failure from discarding a whole run
            output[name] = error_result(exc)
    return output


async def run(args: argparse.Namespace) -> Path:
    if not args.allow_external_calls:
        raise ValueError(
            "This evaluation sends prompts, answers, and retrieved excerpts to Groq. "
            "Review the data policy, then rerun with --allow-external-calls."
        )

    validator = BACKEND_DIR / "scripts" / "validate_contract_evaluation_dataset.py"
    validation = subprocess.run(
        [sys.executable, str(validator), "--dataset", str(args.dataset)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if validation.returncode != 0:
        raise ValueError(
            "Ground-truth validation failed. Run validate_contract_evaluation_dataset.py "
            "directly to inspect the local validation errors."
        )
    # Importing the workflow initializes the vector store. Keep --help and
    # unapproved runs side-effect free, and only load it after the explicit gate.
    from app.agent.graph import procurement_workflow
    from app.core import database
    from app.core.config import settings
    from app.models.models import Contract
    from app.services.telemetry import request_scope

    if not settings.GROQ_API_KEY.strip():
        raise ValueError("GROQ_API_KEY is not configured; no evaluation calls were made.")

    records = load_dataset(args.dataset)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be greater than zero.")
        records = records[:args.limit]

    run_id = args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise ValueError("Invalid run ID format.")
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "results.jsonl"
    summary_path = run_dir / "summary.json"

    metrics, embedding_error = build_metrics(
        settings.GROQ_API_KEY,
        settings.LLM_MODEL_NAME,
        settings.EMBEDDING_MODEL_NAME,
    )

    await database.ensure_active_engine()
    metric_totals: dict[str, list[float]] = defaultdict(list)
    record_statuses: dict[str, int] = defaultdict(int)

    try:
        async with result_path.open("x", encoding="utf-8") as output_file:
            for index, record in enumerate(records, 1):
                request_id = uuid.uuid4().hex
                result: dict[str, Any] = {
                    "run_id": run_id,
                    "question_id": record.get("question_id"),
                    "category": record.get("category"),
                    "difficulty": record.get("difficulty"),
                    "source_document": record.get("source_document"),
                    "ground_truth_status": record.get("ground_truth_status"),
                    "request_id": request_id,
                    "generation_mode": None,
                    "response": None,
                    "retrieved_contexts": [],
                    "retrieved_context_ids": [],
                    "metrics": {name: unavailable("Workflow not run.") for name in METRIC_NAMES},
                }
                try:
                    async with database.async_session_factory() as db:
                        supplier_id, mapping_error = await resolve_supplier_id(db, record, Contract)
                        if mapping_error:
                            result["status"] = "skipped_unmapped_source"
                            result["skip_reason"] = mapping_error
                        else:
                            with request_scope(request_id):
                                state = await procurement_workflow.execute(
                                    supplier_id=supplier_id,
                                    task_type="general_assistant",
                                    user_query=str(record.get("question") or ""),
                                    db=db,
                                )
                            answer = str(state.get("analysis_summary") or "")
                            evidence = state.get("contract_evidence") or []
                            contexts = [str(item.get("text") or "") for item in evidence if item.get("text")]
                            result.update({
                                "status": "completed",
                                "generation_mode": state.get("generation_mode"),
                                "model_name": settings.LLM_MODEL_NAME if state.get("generation_mode") == "groq" else None,
                                "llm_calls": state.get("llm_calls", 0),
                                "trace_id": state.get("trace_id"),
                                "response": answer,
                                "retrieved_contexts": contexts,
                                "retrieved_context_ids": [item.get("chunk_id") for item in evidence if item.get("chunk_id")],
                                "retrieved_document_ids": [item.get("documentId") for item in evidence if item.get("documentId")],
                            })
                            result["metrics"] = await score_case(
                                metrics, record, answer, contexts, embedding_error
                            )
                            for metric_name, metric_result in result["metrics"].items():
                                if metric_result.get("status") == "scored":
                                    metric_totals[metric_name].append(metric_result["score"])
                except Exception as exc:
                    result["status"] = "error"
                    result["error_type"] = type(exc).__name__
                    result["metrics"] = {name: error_result(exc) for name in METRIC_NAMES}

                record_statuses[result["status"]] += 1
                output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                output_file.flush()
                print(f"[{index}/{len(records)}] {record.get('question_id')}: {result['status']}")
    finally:
        await database.engine.dispose()

    summary = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "record_count": len(records),
        "record_status_counts": dict(record_statuses),
        "metrics": {
            name: {
                "scored_count": len(metric_totals[name]),
                "mean": sum(metric_totals[name]) / len(metric_totals[name]) if metric_totals[name] else None,
            }
            for name in METRIC_NAMES
        },
        "evaluator": {"provider": "groq", "model": settings.LLM_MODEL_NAME},
        "content_capture": False,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, help="Evaluate only the first N records.")
    parser.add_argument("--run-id", help="Optional safe run ID supplied by the development API.")
    parser.add_argument(
        "--allow-external-calls",
        action="store_true",
        help="Required: permits sending prompts, answers, and retrieved excerpts to Groq for generation and scoring.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    try:
        run_dir = asyncio.run(run(args))
    except Exception as exc:
        print(f"Evaluation did not complete ({type(exc).__name__}). Check configuration and local logs.", file=sys.stderr)
        return 1
    print(f"Evaluation artifacts saved under: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
