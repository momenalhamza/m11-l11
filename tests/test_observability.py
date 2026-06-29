"""YOUR tests for the observability layer.

Three substantive tests covering the three middleware behaviors:
  1. X-Request-ID header is present and non-empty after a request.
  2. requests_total counter increments for the (path, status) pair.
  3. The structured log line contains the same request_id as the response header.
"""

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _scrape_metrics() -> str:
    return client.get("/metrics").text


def test_request_id_header_is_set_and_non_empty():
    """X-Request-ID response header is present and has at least 8 characters."""
    resp = client.get("/healthz")
    header = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
    assert header is not None, "X-Request-ID header missing from response"
    assert len(header) >= 8, f"X-Request-ID too short: {header!r}"


def test_requests_total_counter_increments_on_request():
    """requests_total{path='/healthz', status='200'} increments after a request."""
    def counter_value(body: str) -> float:
        pattern = re.compile(
            r'^requests_total\{[^}]*path="/healthz"[^}]*\}\s+([0-9.eE+-]+)',
            re.MULTILINE,
        )
        m = pattern.search(body)
        return float(m.group(1)) if m else 0.0

    before = counter_value(_scrape_metrics())
    client.get("/healthz")
    after = counter_value(_scrape_metrics())
    assert after >= before + 1, (
        f"Counter did not increment (before={before}, after={after})"
    )


def test_structured_log_contains_matching_request_id(caplog):
    """The JSON log line carries the same request_id that appears in the response header."""
    with caplog.at_level(logging.INFO):
        resp = client.get("/healthz")

    response_rid = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
    assert response_rid, "X-Request-ID header missing; cannot verify log correlation"

    found = False
    for record in caplog.records:
        try:
            obj = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if obj.get("request_id") == response_rid:
            found = True
            break

    assert found, (
        f"No JSON log line carried request_id={response_rid!r}. "
        "Check middleware ordering: RequestIdMiddleware must be outermost."
    )
