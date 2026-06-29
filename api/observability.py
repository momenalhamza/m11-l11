"""Observability layer for the M10 backend.

This module is where you (the learner) declare the three Prometheus metric
families and implement the three ASGI middleware classes that the autograder
exercises through the FastAPI app.

What lives here, and why:

  - Three metric families. A counter for request volume by (path, status), a
    histogram for request latency by path, and a gauge for in-flight requests.
    Together they answer "how much traffic, how slow, how concurrent."

  - Three middlewares. A request-id layer that attaches a per-request
    correlation id to the response and to the logging context. A
    structured-logging layer that emits one JSON line per response. A metrics
    layer that increments the counter, observes the latency histogram, and
    brackets the request with the in-flight gauge.

  Ordering matters: request-id is outermost (so it wraps the logging line),
  logging is middle, metrics is innermost (closest to the route).

Where to put what:

  - Declarations at MODULE SCOPE. If you declare a Counter / Histogram / Gauge
    inside a function or inside a middleware __call__, you will hit
    `Duplicated timeseries in CollectorRegistry` on the second request --
    every request re-runs the function. Module scope means the registry sees
    the declaration once at import time.

  - Label cardinality matters. The Lab's `requests_total` Counter uses
    exactly two labels: {path, status}. Do NOT add user-id, query-text,
    full-URL, or any other unbounded label.

Methodology pointers:

  - Reading sections 6-10 cover middleware, metric types, label cardinality.
  - See Common Pitfalls #1-#4 in the lab guide.
"""

import json
import logging
import time
import uuid
from contextvars import ContextVar

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Module-scope metric declarations — registry sees these once at import time.
# ---------------------------------------------------------------------------

requests_total = Counter(
    "requests_total",
    "Total HTTP requests by path and status code.",
    ["path", "status"],
)

request_latency_seconds = Histogram(
    "request_latency_seconds",
    "HTTP request latency in seconds by path.",
    ["path"],
    # Default Prometheus latency buckets as required by the lab guide.
)

inflight_requests = Gauge(
    "inflight_requests",
    "Number of HTTP requests currently being processed.",
)

# ContextVar so the request_id set by RequestIdMiddleware is readable by
# StructuredLoggingMiddleware in the same async task context.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

_logger = logging.getLogger("m11.api")


# ---------------------------------------------------------------------------
# RequestIdMiddleware — outermost layer
# ---------------------------------------------------------------------------

class RequestIdMiddleware:
    """Generate a UUID per request; expose it via ContextVar + response header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        request_id_var.set(request_id)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_header)


# ---------------------------------------------------------------------------
# StructuredLoggingMiddleware — middle layer
# ---------------------------------------------------------------------------

class StructuredLoggingMiddleware:
    """Emit one JSON log line per response with request_id, path, status, latency_ms."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        path = scope.get("path", "")
        status_code = 0

        async def capture_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        await self.app(scope, receive, capture_send)

        elapsed_ms = (time.perf_counter() - start) * 1000
        log_record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "INFO",
            "request_id": request_id_var.get(""),
            "path": path,
            "status": status_code,
            "latency_ms": round(elapsed_ms, 3),
        }
        _logger.info(json.dumps(log_record))


# ---------------------------------------------------------------------------
# MetricsMiddleware — innermost layer (closest to the route)
# ---------------------------------------------------------------------------

class MetricsMiddleware:
    """Track in-flight requests, request count, and latency via Prometheus metrics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        inflight_requests.inc()
        start = time.perf_counter()
        status_code = 0

        try:
            async def capture_send(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message.get("status", 0)
                await send(message)

            await self.app(scope, receive, capture_send)
        finally:
            elapsed = time.perf_counter() - start
            inflight_requests.dec()
            requests_total.labels(path=path, status=str(status_code)).inc()
            request_latency_seconds.labels(path=path).observe(elapsed)
