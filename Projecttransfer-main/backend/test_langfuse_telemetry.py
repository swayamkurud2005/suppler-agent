"""Opt-in integration test that verifies a trace can be read back from Langfuse."""

import os
import time
import uuid

import pytest

from app.core.config import settings
from app.services import telemetry


def test_langfuse_trace_is_ingested_and_readable():
    if os.getenv("RUN_LANGFUSE_INTEGRATION") != "1":
        pytest.skip("Set RUN_LANGFUSE_INTEGRATION=1 to write a trace to Langfuse.")
    if not settings.langfuse_enabled:
        pytest.skip("Langfuse project credentials are not configured.")

    client = telemetry._get_client()
    assert client is not None
    assert client.auth_check(), "Langfuse rejected the configured project credentials."

    with telemetry.request_scope(f"lf-test-{uuid.uuid4().hex[:12]}"):
        with telemetry.request_trace(
            "supplier360.langfuse_verification",
            metadata={"verification": "integration_test"},
            content_input="Langfuse telemetry verification",
        ) as trace:
            trace_id = trace.trace_id

    assert trace_id, "No Langfuse trace ID was created."
    client.flush()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = client.api.observations.get_many(
            trace_id=trace_id,
            limit=100,
            fields="core,basic",
        )
        if any(item.name == "supplier360.langfuse_verification" for item in result.data):
            return
        time.sleep(0.5)

    pytest.fail(f"Langfuse did not return verification trace {trace_id} after flush.")
