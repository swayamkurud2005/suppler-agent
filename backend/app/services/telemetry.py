"""Optional, privacy-conscious Langfuse tracing helpers."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import re
import threading
import time
import uuid
from typing import Any, Iterator

from app.core.config import settings

logger = logging.getLogger("supplier360.telemetry")

_request_id: ContextVar[str | None] = ContextVar("supplier360_request_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("supplier360_trace_id", default=None)
_client: Any = None
_client_checked = False
_client_lock = threading.Lock()


def current_request_id() -> str | None:
    return _request_id.get()


def current_trace_id() -> str | None:
    return _trace_id.get()


@contextmanager
def request_scope(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def _get_client():
    """Initialize the SDK only when credentials are configured."""
    global _client, _client_checked
    if not settings.langfuse_enabled:
        return None
    if _client_checked:
        return _client

    with _client_lock:
        if _client_checked:
            return _client
        _client_checked = True
        try:
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY.strip(),
                secret_key=settings.LANGFUSE_SECRET_KEY.strip(),
                base_url=settings.LANGFUSE_BASE_URL.strip() or None,
                tracing_enabled=True,
            )
        except ImportError:
            logger.warning("Langfuse credentials are set but the optional SDK is not installed.")
        except Exception as exc:
            # Never include exception text: it can contain request or configuration data.
            logger.warning("Langfuse client initialization failed (%s).", type(exc).__name__)
    return _client


def _redact_content(value: str) -> str:
    """Best-effort redaction for explicitly enabled content previews."""
    text = value[:2000]
    patterns = (
        (r"(?i)(api[_ -]?key|secret|password|authorization|bearer)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]"),
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]"),
        (r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", "[PHONE]"),
        (r"(?i)(?:₹|INR|USD|EUR|\$)\s?\d[\d,]*(?:\.\d+)?", "[AMOUNT]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


class _Observation:
    def __init__(self, span: Any = None):
        self._span = span

    def update(self, *, metadata: dict | None = None, content_input: str | None = None,
               content_output: str | None = None, usage_details: dict | None = None,
               level: str | None = None, status_message: str | None = None) -> None:
        if self._span is None:
            return
        values: dict[str, Any] = {}
        if metadata:
            values["metadata"] = metadata
        if settings.LANGFUSE_CAPTURE_CONTENT:
            if content_input is not None:
                values["input"] = _redact_content(content_input)
            if content_output is not None:
                values["output"] = _redact_content(content_output)
        if usage_details:
            values["usage_details"] = usage_details
        if level:
            values["level"] = level
        if status_message:
            values["status_message"] = status_message[:120]
        if values:
            try:
                self._span.update(**values)
            except Exception as exc:
                logger.warning("Langfuse observation update failed (%s).", type(exc).__name__)


@contextmanager
def observation(name: str, *, metadata: dict | None = None, as_type: str = "span",
                model: str | None = None, content_input: str | None = None,
                trace_context: dict | None = None) -> Iterator[_Observation]:
    """Create a nested span when Langfuse is configured; otherwise be a no-op."""
    client = _get_client()
    started = time.perf_counter()
    if client is None:
        yield _Observation()
        return

    params: dict[str, Any] = {"as_type": as_type, "name": name}
    if metadata:
        params["metadata"] = metadata
    if model:
        params["model"] = model
    if settings.LANGFUSE_CAPTURE_CONTENT and content_input is not None:
        params["input"] = _redact_content(content_input)
    if trace_context:
        params["trace_context"] = trace_context

    try:
        manager = client.start_as_current_observation(**params)
        span = manager.__enter__()
    except Exception as exc:
        # Telemetry failures must not break procurement requests.
        logger.warning("Langfuse observation could not start for %s (%s).", name, type(exc).__name__)
        yield _Observation()
        return

    wrapped = _Observation(span)
    try:
        yield wrapped
    except BaseException as exc:
        wrapped.update(
            metadata={"status": "error", "error_type": type(exc).__name__},
            level="ERROR",
            status_message=type(exc).__name__,
        )
        wrapped.update(metadata={"duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception as telemetry_exc:
            # Keep the original workflow exception as the one callers see.
            logger.warning("Langfuse observation could not close for %s (%s).", name, type(telemetry_exc).__name__)
        raise
    else:
        wrapped.update(metadata={"status": "success"})
        wrapped.update(metadata={"duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            # Telemetry is optional and must never fail an otherwise successful request.
            logger.warning("Langfuse observation could not close for %s (%s).", name, type(exc).__name__)


class _TraceHandle:
    def __init__(self, trace_id: str | None, root: _Observation):
        self.trace_id = trace_id
        self._root = root

    def update(self, *, metadata: dict | None = None, content_input: str | None = None,
               content_output: str | None = None) -> None:
        safe_metadata = {key: value for key, value in (metadata or {}).items() if value is not None}
        self._root.update(metadata=safe_metadata, content_input=content_input, content_output=content_output)


@contextmanager
def request_trace(name: str, *, metadata: dict | None = None,
                  content_input: str | None = None) -> Iterator[_TraceHandle]:
    """Open a root trace for one AI workflow request, if configured."""
    client = _get_client()
    if client is None:
        yield _TraceHandle(None, _Observation())
        return

    trace_id = uuid.uuid4().hex
    token = _trace_id.set(trace_id)
    trace_metadata = {"request_id": current_request_id() or "unavailable", **(metadata or {})}
    try:
        with observation(
            name,
            metadata=trace_metadata,
            content_input=content_input,
            trace_context={"trace_id": trace_id},
        ) as root:
            yield _TraceHandle(trace_id, root)
    finally:
        _trace_id.reset(token)


def usage_details(response: Any) -> dict | None:
    """Translate only token counts actually returned by the LLM provider."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    values = {
        "input": getattr(usage, "prompt_tokens", None),
        "output": getattr(usage, "completion_tokens", None),
        "total": getattr(usage, "total_tokens", None),
    }
    actual = {key: int(value) for key, value in values.items() if isinstance(value, int)}
    return actual or None


def shutdown_telemetry() -> None:
    client = _client
    if client is None:
        return
    try:
        client.shutdown()
    except Exception as exc:
        logger.warning("Langfuse shutdown failed (%s).", type(exc).__name__)
