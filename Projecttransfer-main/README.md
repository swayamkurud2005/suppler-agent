# Agentic Supplier Contract Intelligence

Evidence-grounded procurement decision support for supplier contracts, operational records, and compatible market benchmarks. The system offers findings and discussion points for a procurement owner; it does not approve or reject suppliers.

## Architecture

- **Frontend:** React 19 and Vite. Pages are under `Frontend/src/pages/`; API calls are under `Frontend/src/services/api/`.
- **API:** FastAPI routes under `backend/app/api/v1/endpoints/`.
- **Data:** SQLAlchemy models and Alembic migrations. PostgreSQL is supported; local SQLite is also supported.
- **Ingestion:** upload validation → PDF/DOCX/TXT parsing → chunking → vector indexing → structured term extraction → SQL persistence.
- **Retrieval:** structured SQL queries plus dense Qdrant (with an in-memory fallback) and in-memory BM25, fused by Reciprocal Rank Fusion (RRF).
- **Agent:** a direct sequential workflow classifies the task, retrieves SQL and contract evidence, synthesizes an answer, and normalizes the response. It calls Groq when configured and otherwise uses a deterministic evidence-aware fallback.
- **Evaluation and observability:** RAGAS runs separately through a command/API restricted to development mode; optional Langfuse tracing records the request, retrieval, generation, and guardrail stages.

## Setup on Windows

Copy the configuration template and edit the local file. The template uses SQLite and leaves provider API keys empty:

```powershell
Copy-Item .env.example backend/.env
notepad backend/.env
```

For local PostgreSQL and Qdrant via Docker, start the services:

```powershell
docker compose up -d postgres qdrant
```

Then set `DATABASE_URL=postgresql+asyncpg://supplier360:supplier360_dev@localhost:5432/supplier360` in `backend/.env`. These compose credentials are for local development only. You may instead leave the SQLite URL from the example. Keep `.env` files private and do not commit credentials.

Install and start the backend from the repository root:

```powershell
py -3 -m venv backend/.venv
backend/.venv/Scripts/Activate.ps1
python -m pip install -r backend/requirements.txt
Set-Location backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell window, start the frontend:

```powershell
Set-Location Frontend
npm ci
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). The backend health endpoint is `http://localhost:8000/health`; interactive API docs are at `http://localhost:8000/docs`.

## Environment variables

The root `.env.example` lists every setting declared by `backend/app/core/config.py`. Settings load `backend/.env` first, then the repository root `.env`; process environment variables take precedence. Configure `GROQ_API_KEY` for LLM generation and RAGAS evaluation, `METALCHARTS_API_KEY` for live metal price refresh, and Langfuse keys only when tracing to a Langfuse project. Keep `LANGFUSE_CAPTURE_CONTENT=false` unless content capture has been reviewed and approved.

## Evaluation and telemetry guides

- [Evaluation guide](EVALUATION_GUIDE.md)
- [Telemetry guide](TELEMETRY_GUIDE.md)
- [Project completion audit](PROJECT_COMPLETION_AUDIT.md)

The checked-in evaluation examples are clearly labeled synthetic fixtures based on project seed data; they are not real supplier ground truth.

## Tests and known limitations

Run the offline test suite from `backend/`:

```powershell
python -m pytest -q test_api.py test_market_prices.py
python scripts/validate_contract_evaluation_dataset.py
```

The test and service verification status, including unavailable external credentials, is recorded in the guides. Evidence citations are preserved from retrieved chunks and prompts require grounded answers, but the project does not implement a separate claim-to-source entailment verifier. BM25 and fallback dense embeddings are in-memory; the configured reranker is not wired into retrieval. Seeded demo records and benchmark values are synthetic.

### Verification recorded for this closure

- `pytest -q test_api.py test_market_prices.py`: **9 passed** on the SQLite fallback, with temporary uploads.
- `python scripts/validate_contract_evaluation_dataset.py`: **passed**, 10 records and source evidence/hash checks.
- PostgreSQL at localhost was unavailable; SQLite fallback was exercised. Langfuse SDK 5.2.0 accepts `host`, but live trace delivery awaits credentials. RAGAS and Node.js/npm are not installed in this environment, so RAGAS scoring and frontend build/browser integration remain unverified.
