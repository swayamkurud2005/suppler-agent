# Langfuse Telemetry Guide

Langfuse is optional. The backend creates one client at FastAPI startup and reuses it. If keys or the SDK are missing, telemetry helpers become no-ops and the application continues using its existing logging and request IDs.

## Configure

Copy the root template to the backend-local environment file and fill only the credentials you have:

```powershell
Copy-Item .env.example backend/.env
notepad backend/.env
```

Set these values from your Langfuse project:

```env
LANGFUSE_SECRET_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_BASE_URL=https://your-langfuse-host
LANGFUSE_CAPTURE_CONTENT=false
```

The SDK receives the host via its `host` argument. Keep the three credentials private. Content capture is disabled by default; if enabled, content is truncated and passed through basic redaction, but this is not a substitute for privacy review.

## What is traced

For AI analysis/assistant requests, the trace is opened by the existing workflow and nests spans for classification, structured SQL retrieval, hybrid retrieval, dense search, BM25, RRF fusion, Groq generation when used, and response normalization. Metadata includes durations, success/error type, result counts, available chunk/document IDs, generation mode, model and token usage when returned by Groq. The implementation does not create tool-call or reranker spans because those stages are not present in the current runtime. Raw prompts and final content are not sent by default.

Every HTTP response carries an `X-Request-ID`; AI workflow responses also carry `X-Trace-ID` when tracing is enabled. Evaluation traces include their run and question IDs, and matching result rows retain the trace ID.

## Verify

1. Configure keys and host in `backend/.env` and keep content capture false.
2. Start the backend and call an AI endpoint, for example:

   ```powershell
   $response = Invoke-WebRequest -Method Post -Uri http://localhost:8000/api/analysis/assistant/query `
     -ContentType 'application/json' `
     -Body '{"supplierId":"SUP-001","message":"What payment terms are recorded?"}'
   $response.Headers['X-Trace-ID']
   ```

3. Read the `X-Trace-ID` response header and find the trace in your Langfuse project. Inspect the nested retrieval and generation spans, durations, and token usage where supported.
4. Temporarily test with missing credentials: the backend should still start and return answers; no Langfuse trace is expected.

## Limitations

Live delivery requires valid project credentials, a reachable Langfuse host, and installed compatible SDK. No live Langfuse project was available during local verification. Errors are isolated and logged by exception type without logging provider exception text. A separate claim-entailment verifier is not implemented, so a trace records the pipeline but does not certify every generated claim.

## Verification status

The installed Langfuse SDK is 5.2.0 and its constructor exposes the configured `host` parameter. The offline API suite passed with Langfuse keys absent, confirming that missing credentials do not prevent startup or answering. A live trace could not be verified because no Langfuse project credentials are configured.
