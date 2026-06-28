"""Smoke test for the Prometheus ``/metrics`` endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from api import metrics as api_metrics
from api.main import app

_QUEUE_COUNTS = {"arq:queue:worker": 4, "arq:queue:bot": 2}


def test_metrics_endpoint_serves_prometheus_format(monkeypatch):
    monkeypatch.setattr(
        api_metrics,
        "queued_job_count",
        AsyncMock(side_effect=lambda queue: _QUEUE_COUNTS.get(queue, 0)),
    )

    with TestClient(app) as client:
        # A non-exempt request so the request counter/histogram get a sample.
        client.get("/this-route-does-not-exist")
        resp = client.get("/metrics")

    assert resp.status_code == 200
    body = resp.text
    assert "api_http_request_duration_seconds" in body
    assert 'api_http_requests_total{method="GET",route="unmatched",status="404"}' in body
    assert 'arq_queue_depth{queue="worker"}' in body
    assert 'arq_queue_depth{queue="bot"}' in body
