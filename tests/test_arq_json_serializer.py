"""Cross-language ARQ contract: the JSON job serializer round-trips, and a job
body produced by the Go API (apigo/enqueue.go) is consumable by arq.

These guard the seam that lets the Go back-office API enqueue `publish` jobs that
the Python `bot` worker consumes (plan: produce-only ARQ interop).
"""

from __future__ import annotations

import json

from arq.jobs import deserialize_job, serialize_job

from shared.tasks import arq_job_deserializer, arq_job_serializer


def test_json_serializer_roundtrip():
    blob = serialize_job(
        "publish", (123,), {}, None, 1_751_299_200_000, serializer=arq_job_serializer
    )
    job = deserialize_job(blob, deserializer=arq_job_deserializer)
    assert job.function == "publish"
    assert list(job.args) == [123]
    assert job.kwargs == {}


def test_go_style_job_body_is_consumable():
    """A body byte-for-byte like apigo/enqueue.go's buildPublishJobBody must
    deserialize to the same job the Python producer would create."""
    body = json.dumps(
        {"t": None, "f": "publish", "a": [123], "k": {}, "et": 1_751_299_200_000}
    ).encode()
    job = deserialize_job(body, deserializer=arq_job_deserializer)
    assert job.function == "publish"
    assert list(job.args) == [123]
    assert job.kwargs == {}


def test_alert_kwargs_roundtrip():
    """The bot's `alert` job carries a tenant_id kwarg; JSON must preserve it."""
    blob = serialize_job(
        "alert", ("hello",), {"tenant_id": 5}, None, 1_751_299_200_000,
        serializer=arq_job_serializer,
    )
    job = deserialize_job(blob, deserializer=arq_job_deserializer)
    assert job.function == "alert"
    assert list(job.args) == ["hello"]
    assert job.kwargs == {"tenant_id": 5}
