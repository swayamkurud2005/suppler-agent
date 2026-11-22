"""Exercise the running Assistant endpoint and read its trace back from Langfuse."""

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.services.telemetry import _get_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Call the FastAPI app in-process using the configured database URL.",
    )
    parser.add_argument("--supplier-id", default="SUP-001")
    parser.add_argument("--message", default="Summarize the key delivery obligations in this supplier's contract.")
    args = parser.parse_args()

    if not settings.langfuse_enabled:
        print("Langfuse is disabled: configure LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.")
        return 2

    client = _get_client()
    if client is None:
        print("Langfuse authentication failed; no Assistant request was sent.")
        return 2

    def finish(code: int) -> int:
        try:
            client.flush()
            client.shutdown()
        except Exception:
            pass
        return code

    if not client.auth_check():
        print("Langfuse authentication failed; no Assistant request was sent.")
        return finish(2)

    session_id = f"telemetry-check-{uuid.uuid4().hex[:16]}"
    body = {
        "supplier_id": args.supplier_id,
        "session_id": session_id,
        "message": args.message,
    }
    try:
        if args.in_process:
            async def call_app():
                from httpx import ASGITransport, AsyncClient

                from app.core import database
                from app.main import app

                async with database.engine.begin() as connection:
                    await connection.run_sync(database.Base.metadata.create_all)
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://supplier360.local",
                    timeout=180,
                ) as app_client:
                    return await app_client.post("/api/analysis/assistant/query", json=body)

            response = asyncio.run(call_app())
        else:
            response = httpx.post(
                f"{args.base_url.rstrip('/')}/api/analysis/assistant/query",
                json=body,
                timeout=180,
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Assistant request failed ({type(exc).__name__}). Check the backend logs.")
        return finish(1)

    trace_id = payload.get("trace_id")
    if not trace_id:
        print("Assistant returned no trace ID. Confirm the backend loaded Langfuse credentials.")
        return finish(1)

    deadline = time.monotonic() + 30
    observations = []
    while time.monotonic() < deadline:
        client.flush()
        result = client.api.observations.get_many(
            trace_id=trace_id,
            limit=100,
            fields="core,basic,io,metadata,model,usage,metrics",
        )
        observations = result.data
        names = {item.name for item in observations}
        if "supplier360.procurement_request" in names:
            break
        time.sleep(0.5)

    names = {item.name for item in observations}
    types = {item.type for item in observations}
    expected = {
        "supplier360.procurement_request",
        "retrieval.contract_hybrid",
        "retrieval.hybrid.primary",
        "llm.groq_generation",
    }
    missing = sorted(expected - names)
    if missing:
        print(f"Langfuse trace {trace_id} is missing expected observations: {', '.join(missing)}")
        return finish(1)
    if "GENERATION" not in types:
        print(f"Langfuse trace {trace_id} has no GENERATION observation.")
        return finish(1)

    root = next(item for item in observations if item.name == "supplier360.procurement_request")
    if getattr(root, "session_id", None) != session_id:
        print(f"Langfuse trace {trace_id} is missing the requested session ID.")
        return finish(1)
    if settings.LANGFUSE_CAPTURE_CONTENT and not (getattr(root, "input", None) and getattr(root, "output", None)):
        print(f"Langfuse trace {trace_id} is missing query/response content while capture is enabled.")
        return finish(1)

    print(f"Verified Assistant trace: {trace_id}")
    print(f"Observations: {len(observations)}; generation recorded; session recorded.")
    if settings.LANGFUSE_CAPTURE_CONTENT:
        print("Query and response content are present.")
    else:
        print("Query/response content capture is disabled; set LANGFUSE_CAPTURE_CONTENT=true to include it.")
    return finish(0)


if __name__ == "__main__":
    raise SystemExit(main())
