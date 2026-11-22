# RAGAS Evaluation Guide

The evaluation runner is an offline/development workflow. It does not execute for normal API requests.

## Method

`backend/scripts/run_ragas_evaluation.py` reads the versioned JSONL dataset, runs each question through the existing Supplier360 workflow, collects the generated answer, contract chunks, structured SQL context and trace IDs, then evaluates single-turn samples with the RAGAS 0.3.9 API. The optional stack is pinned in `backend/requirements-evaluation.txt`.

Implemented metrics:

- **Faithfulness** — whether answer claims are supported by retrieved contexts.
- **Answer Relevancy** (`ResponseRelevancy`) — semantic relevance of the response to the question; requires the local embedding model to be available.
- **Context Precision** (`LLMContextPrecisionWithReference`) — relevance/ranking of retrieved contexts against a reference answer.
- **Context Recall** (`LLMContextRecall`) — coverage of reference information by retrieved contexts.

Reference-based metrics are unavailable when a record has no supported answer/reference or no contexts. Answer relevancy is unavailable when local evaluator embeddings are unavailable. Provider errors are recorded as errors; no scores are synthesized.

The ten starter records are labeled synthetic and cite exact source snippets/hashes from `backend/app/db/seed.py` or `backend/app/services/vector_store.py`. They are project demonstration fixtures, not real executed contracts or ground truth about real suppliers. Review the dataset before use. The runner sends prompts, answers, and retrieved evidence to Groq only after the explicit `--allow-external-calls` opt-in.

## Run and export

From `backend/` in Windows PowerShell:

```powershell
python -m pip install -r requirements-evaluation.txt
python scripts/validate_contract_evaluation_dataset.py
```

Set `GROQ_API_KEY` in `backend/.env`, then run a full evaluation:

```powershell
python scripts/run_ragas_evaluation.py --allow-external-calls
```

Run a smaller smoke evaluation after reviewing data transfer:

```powershell
python scripts/run_ragas_evaluation.py --limit 2 --allow-external-calls
```

Each run creates `backend/runtime/evaluations/results/<run_id>/` with:

- `results.jsonl` — per-question answer, retrieved contexts and IDs, metric status/scores, evaluation timestamp, run ID, and trace ID.
- `results.csv` — convenient tabular export; contexts and metric details are JSON-encoded cells.
- `summary.json` — record statuses, metric means for actually scored records, and evaluator model.

The evaluation API under `/api/evaluations` is hidden unless `DEBUG=true`, requires explicit external-call acknowledgement, and returns summary metadata rather than answer/context content. Evaluation records preserve `run_id`, `question_id`, `trace_id`, generation metadata, and timestamps. When Langfuse is configured, each request trace also carries `evaluation_run_id` and `evaluation_question_id` metadata.

## Limitations

- A completed run requires Groq credentials and network access. RAGAS judges use Groq; answer relevancy additionally needs the configured embedding model available locally.
- The starter dataset is small and synthetic. Replace or extend it with reviewed, access-controlled real ground truth before drawing procurement-quality conclusions.
- RAGAS scores are indicators for regression analysis, not proof of factual correctness or supplier performance.

## Verification status

The ten-record dataset passed `scripts/validate_contract_evaluation_dataset.py`: all records parse, IDs are unique, and declared fixture hashes and snippets match their sources. The optional `ragas` package is absent from the current environment, so metric imports and an actual score run were not executed. `GROQ_API_KEY` is also absent. Install the optional requirements and configure the key before running the evaluator.
