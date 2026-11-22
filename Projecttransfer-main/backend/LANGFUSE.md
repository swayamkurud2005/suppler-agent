# Supplier360 Langfuse tracing

Langfuse tracing is optional. The FastAPI lifespan initializes the SDK client from the existing environment-backed settings. When both project keys are configured, each procurement workflow creates one agent trace with nested routing, SQL/hybrid retrieval, embedding, Groq generation, and guardrail observations. Missing credentials or telemetry failures do not fail the Assistant request.

Required environment variables:

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

For EU, US, Japan, or self-hosted projects, set `LANGFUSE_BASE_URL` to that project's host. Keys must remain in the backend environment and must not be committed.

Query and response content is opt-in. Set `LANGFUSE_CAPTURE_CONTENT=true` only when supplier questions and generated answers may be sent to Langfuse. When disabled, traces still include timing, model, token usage, request/supplier metadata, and retrieved document references, but omit query and response text. Content that is enabled is truncated and redacted by the telemetry helper.

The Assistant accepts an optional `sessionId` or `session_id`. The frontend keeps one session ID for the current chat view and sends it with each turn; request IDs remain separate for per-request correlation.

## Verify an application request

Start the backend from `backend/` with the environment variables loaded:

```powershell
.\venv\Scripts\Activate.ps1
$env:DEBUG = "true"
$env:LANGFUSE_CAPTURE_CONTENT = "true"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another PowerShell terminal, from `backend/`, run:

```powershell
python scripts/verify_langfuse_assistant.py --supplier-id SUP-001
```

The script sends a real request to `/api/analysis/assistant/query`, then reads its trace back from Langfuse and checks for the root agent trace, hybrid retrieval, and Groq generation. It calls the configured Groq provider and sends the request's supplier context to that provider as the Assistant normally does.

The SDK round-trip integration test verifies trace ingestion independently:

```powershell
$env:DEBUG = "true"
$env:RUN_LANGFUSE_INTEGRATION = "1"
python -m pytest test_langfuse_telemetry.py -q
```

Both checks require valid Langfuse project credentials in the backend environment. The Assistant check also requires a running backend and its configured database, vector store, and Groq access.
