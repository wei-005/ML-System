from __future__ import annotations

from datetime import datetime, timezone
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_system.cloud_tasks import PayloadEncodingError, create_http_task


def test_str_payload_is_encoded_and_sets_header():
    request = create_http_task(
        parent="projects/demo/locations/us-central1/queues/default",
        url="https://example.com/run",
        payload="hello",
    )

    http_request = request["task"]["http_request"]
    assert http_request["body"] == b"hello"
    assert http_request["headers"]["Content-Type"].startswith("text/plain")


def test_mapping_payload_is_json_encoded():
    request = create_http_task(
        parent="projects/demo/locations/us/queues/default",
        url="https://example.com/run",
        payload={"name": "Ada", "age": 37},
    )

    http_request = request["task"]["http_request"]
    assert http_request["body"] == b'{"name":"Ada","age":37}'
    assert http_request["headers"]["Content-Type"].startswith("application/json")


def test_payload_encoding_error_for_unserialisable_object():
    class Uns:  # pragma: no cover - minimal repr
        pass

    with pytest.raises(PayloadEncodingError):
        create_http_task(
            parent="projects/demo/locations/us/queues/default",
            url="https://example.com/run",
            payload=Uns(),
        )


def test_schedule_time_prefers_explicit_datetime():
    target = datetime(2030, 1, 1, tzinfo=timezone.utc)
    request = create_http_task(
        parent="projects/demo/locations/us/queues/default",
        url="https://example.com/run",
        schedule_time=target,
    )

    assert request["task"]["schedule_time"] == {"seconds": int(target.timestamp()), "nanos": 0}


def test_invalid_arguments_raise_value_error():
    with pytest.raises(ValueError):
        create_http_task(parent="", url="https://example.com")
    with pytest.raises(ValueError):
        create_http_task(parent="projects/demo/queues/q", url="")
    with pytest.raises(ValueError):
        create_http_task(
            parent="projects/demo/queues/q",
            url="https://example.com",
            schedule_time=datetime.now(),
            in_seconds=10,
        )
