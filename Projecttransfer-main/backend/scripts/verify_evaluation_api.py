"""Exercise the real evaluation router and configured RAGAS worker once.

Requires --allow-external-calls because the evaluator sends application content
to Groq. Uses the same router and settings as the backend without running the
application startup seeder.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from fastapi import FastAPI

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.endpoints.evaluations import router


async def verify(allow_external_calls: bool, limit: int, run_id: str | None = None) -> int:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/evaluations")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://supplier360.local", timeout=1800) as client:
        if run_id is None:
            response = await client.post(
                "/api/v1/evaluations/runs",
                json={"limit": limit, "allow_external_calls": allow_external_calls},
            )
            response.raise_for_status()
            run_id = response.json()["run_id"]

        run_response = await client.get(f"/api/v1/evaluations/runs/{run_id}")
        run_response.raise_for_status()
        run = run_response.json()["data"]

        deadline = time.monotonic() + 1800
        while run["status"] in {"queued", "running"} and time.monotonic() < deadline:
            await asyncio.sleep(2)
            run_response = await client.get(f"/api/v1/evaluations/runs/{run_id}")
            run_response.raise_for_status()
            run = run_response.json()["data"]

        records_response = await client.get(f"/api/v1/evaluations/runs/{run_id}/records")
        records_response.raise_for_status()
        records = records_response.json()["data"]
        scores = [
            {"question_id": row.get("question_id"), "metrics": row.get("metrics", {})}
            for row in records
        ]
        print(json.dumps({"run": run, "records": scores}, indent=2))
        if run["status"] != "completed":
            return 1
        return 0 if any(
            metric.get("status") == "scored"
            for row in records
            for metric in (row.get("metrics") or {}).values()
        ) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-calls", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--run-id", help="Poll an existing run without starting a new evaluation.")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    if args.run_id is None and not args.allow_external_calls:
        parser.error("--allow-external-calls is required when starting a new evaluation")
    return asyncio.run(verify(args.allow_external_calls, args.limit, args.run_id))


if __name__ == "__main__":
    sys.exit(main())
