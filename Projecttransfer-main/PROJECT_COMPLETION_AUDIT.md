# Project Completion Audit

Inspected the FastAPI backend, React/Vite frontend, SQLAlchemy models and migrations, ingestion and retrieval services, agent workflow, evaluation scripts, and telemetry. Findings describe the checked-in implementation; seeded records and the evaluation starter set are explicitly synthetic.

| Component | Status | Existing Implementation | Pending Work |
|---|---|---|---|
| RAG | PARTIALLY IMPLEMENTED | Document parsing and chunking in `backend/app/services/document_parser.py` and `backend/app/services/chunking.py`; ingestion/indexing in `backend/app/services/ingestion.py`; Qdrant with in-memory fallback in `backend/app/services/vector_store.py`; dense + in-memory BM25 with Reciprocal Rank Fusion in `backend/app/services/hybrid_retriever.py`. | BM25 is an in-memory implementation rather than an external index; validate retrieval quality against real uploaded and indexed contracts. The reranker setting exists but no reranking stage is wired into retrieval. |
| Agents | PARTIALLY IMPLEMENTED | Direct sequential workflow in `backend/app/agent/graph.py`; routing, SQL retrieval, hybrid clause retrieval, synthesis, and normalization in `backend/app/agent/nodes.py`. It is a Python sequence, not a compiled LangGraph graph. | The workflow has no independent tool-call loop; `tool_calls` is currently reported as zero. Tighten tests around routing and fallback behavior. |
| Evidence verification | PARTIALLY IMPLEMENTED | `guardrail_node` in `backend/app/agent/nodes.py` normalizes finding/evidence shapes, and the synthesis prompt requires source-grounded claims. Retrieved chunks retain document/page/section metadata. | No separate claim-to-source entailment verifier is present; normalization is not proof that every generated claim is supported. Add a dedicated verifier only if the product requires claim-level checks. |
| RAGAS | PARTIALLY IMPLEMENTED | `backend/scripts/run_ragas_evaluation.py` uses the RAGAS 0.3.9 single-turn metric interfaces: Faithfulness, ResponseRelevancy, LLMContextPrecisionWithReference, and LLMContextRecall. `backend/requirements-evaluation.txt` pins the optional stack; a development-only API is in `backend/app/api/v1/endpoints/evaluations.py`. Ten source-checked synthetic records, JSONL output, CSV export, per-record timestamps, run IDs, and trace IDs are included. | The optional RAGAS package is not installed in the current environment and Groq credentials are absent, so no score run was possible. Live evaluation remains to be run after installing the optional stack and configuring credentials. |
| Langfuse | PARTIALLY IMPLEMENTED | Optional singleton client and safe span wrappers in `backend/app/services/telemetry.py`; workflow, SQL, hybrid retrieval, and Groq generation spans in `backend/app/agent/graph.py`, `backend/app/agent/nodes.py`, and `backend/app/services/hybrid_retriever.py`. | Startup initialization and the SDK's `host` configuration parameter were corrected. Credentials are still required to verify delivery to a live Langfuse project; content capture remains disabled by default. |
| Logging and tracing | PARTIALLY IMPLEMENTED | Request correlation IDs in `backend/app/main.py`; module loggers across services; workflow trace IDs returned by analysis APIs; duration, error type, chunk IDs/counts, model, and available token usage recorded by telemetry wrappers. | Langfuse telemetry is optional, so without credentials only existing logs and request IDs remain. Retrieval has no separate reranker span because no reranker is executed. |

## Architecture notes

- Backend: FastAPI routes are registered in `backend/app/api/v1/api.py`; SQLAlchemy models are in `backend/app/models/models.py`, with Alembic migrations under `backend/migrations/`. PostgreSQL is the configured database with a local SQLite fallback in `backend/app/core/database.py`.
- Frontend: React 19 and Vite, with supplier, contract, purchase, performance, report, evidence, and assistant API clients under `Frontend/src/services/api/` and views under `Frontend/src/pages/`.
- Retrieval and generation: the workflow combines structured SQL facts with Qdrant/in-memory dense retrieval and BM25. The synthesis node calls Groq when configured and otherwise uses deterministic fallback behavior. The current configured response model is in `backend/app/core/config.py`.
- Evaluation: optional dependencies are deliberately separate from the application runtime. Dataset ground truth is source-derived from project seed fixtures and labeled synthetic; it is not evidence about real suppliers.
- Sensitive content: Langfuse content capture defaults to false. The trace metadata uses IDs, counts, statuses, and model metadata; enabling content capture is an explicit local setting and should be reviewed for the organization's data policy.

## Final closure checklist

### Implemented and verified

- Nine offline API integration and market-price tests passed on the SQLite fallback (`9 passed`). This included startup, supplier/contract/performance reads, contract analysis and assistant retrieval, upload ingestion, upload type/size rejection, unavailable-metric behavior, and missing-MetalCharts-key behavior.
- The evaluation dataset validator passed: 10 unique records, two source files, matching source hashes, and evidence snippets checked against their declared source.
- The Langfuse 5.2.0 constructor was inspected locally; it accepts `host`. Application tests started with no Langfuse credentials, exercising the optional no-client path.
- PostgreSQL was unavailable at `localhost:5432`; after fixing the stale session-factory fallback path, the offline integration suite passed using SQLite.

### Implemented but awaiting API credentials

- RAGAS score generation needs the optional evaluation dependencies and `GROQ_API_KEY`. No GROQ or MetalCharts API key is configured in this workspace.
- Live Langfuse delivery needs `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and a reachable `LANGFUSE_BASE_URL`.

### Implemented but awaiting external service verification

- PostgreSQL connectivity and Qdrant Cloud were not verified because no local Docker command or cloud credentials were available.
- Frontend-to-backend browser integration was not run because Node.js/npm are unavailable in this environment.

### Not implemented / deferred

- Claim-to-source entailment verification is not implemented; citations are retrieved evidence metadata and prompt constraints, not formal proof of entailment.
- Reranking is not wired into the runtime retrieval pipeline. There are no reranker spans.
- A representative, reviewed real-supplier evaluation corpus is deferred; the checked-in starter dataset is synthetic seed data.

## Running evaluation

From `backend/`, install the optional stack and validate the dataset:

```powershell
pip install -r requirements-evaluation.txt
python scripts/validate_contract_evaluation_dataset.py
```

Configure `GROQ_API_KEY` in the backend `.env`, review the dataset/data-transfer policy, then run:

```powershell
python scripts/run_ragas_evaluation.py --allow-external-calls
```

The runner writes `results.jsonl`, `results.csv`, and `summary.json` under `backend/runtime/evaluations/results/<run_id>/`. The JSONL and CSV include per-record question, answer, retrieved contexts, metric outcomes, and evaluation timestamp. Each metric can be unavailable or error when its required reference, contexts, local embeddings, or provider call is unavailable; scores are never substituted.

## Langfuse setup

Copy the placeholders from root `.env.example` into `backend/.env` (or the root `.env` read by settings), replace them with the project credentials and host, and keep `LANGFUSE_CAPTURE_CONTENT=false` unless content capture has been approved. The client initializes once during FastAPI startup and is reused. Missing credentials or SDK installation leave telemetry as a no-op and preserve application behavior.
