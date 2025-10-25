"""Helpers for constructing Google Cloud Tasks payloads.

The real Google Cloud Tasks client is not available in the execution
environment, so the helpers in this module focus on building the request
payload that would normally be sent to ``CloudTasksClient.create_task``.

Historically our internal helper only handled bytes payloads.  When the
payload was supplied as a string or a Python mapping the helper forwarded it
unchanged, leaving it up to the Google client to perform validation.  The
client requires the body to be bytes which resulted in the somewhat opaque
"Error creating cloud task" message being raised.  The functions below make the
behaviour explicit and provide much more helpful error messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple, Union

__all__ = ["create_http_task", "PayloadEncodingError"]


class PayloadEncodingError(TypeError):
    """Raised when a payload cannot be serialised into bytes."""


_JSON_LIKE_TYPES = (Mapping, list, tuple, set)


def _normalise_method(method: Union[str, Any]) -> str:
    if isinstance(method, str):
        method = method.strip().upper()
    else:
        method = str(method).strip().upper()
    if not method:
        raise ValueError("HTTP method must be a non-empty string")
    return method


def _encode_payload(payload: Any) -> Tuple[Optional[bytes], Optional[str]]:
    """Return the body bytes and default content type for ``payload``.

    ``payload`` may be ``bytes``/``bytearray`` (returned unchanged), a
    string (encoded as UTF-8) or a JSON serialisable object.  The caller can
    override the suggested content type by supplying ``headers`` with an
    explicit ``Content-Type`` key.
    """

    if payload is None:
        return None, None

    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload), None

    if isinstance(payload, str):
        return payload.encode("utf-8"), "text/plain; charset=utf-8"

    if isinstance(payload, _JSON_LIKE_TYPES):
        try:
            json_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:  # pragma: no cover - json raises ValueError rarely
            raise PayloadEncodingError("Payload cannot be serialised to JSON") from exc
        return json_payload.encode("utf-8"), "application/json; charset=utf-8"

    # Fallback: try JSON encoding for arbitrary objects that provide ``__iter__`` or ``__dict__``.
    try:
        json_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PayloadEncodingError(
            "Payload of type %s is not supported; provide bytes, string or JSON serialisable object"
            % type(payload).__name__
        ) from exc
    return json_payload.encode("utf-8"), "application/json; charset=utf-8"


@dataclass(frozen=True)
class _Timestamp:
    """Simple representation of a protobuf ``Timestamp`` message.

    Using a dataclass keeps the representation easy to inspect in tests while
    remaining serialisable to a ``dict`` when talking to the Google client.
    """

    seconds: int
    nanos: int

    def to_dict(self) -> Dict[str, int]:
        return {"seconds": self.seconds, "nanos": self.nanos}


def _to_timestamp(dt: datetime) -> _Timestamp:
    if dt.tzinfo is None:
        # Assume UTC for naive datetimes – this mirrors the behaviour of
        # ``datetime.utcnow`` which most call sites use.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    total_seconds = dt.timestamp()
    seconds = int(total_seconds)
    nanos = int(round((total_seconds - seconds) * 1_000_000_000))
    if nanos == 1_000_000_000:
        seconds += 1
        nanos = 0
    return _Timestamp(seconds=seconds, nanos=nanos)


def _resolve_schedule(
    *,
    schedule_time: Optional[datetime] = None,
    in_seconds: Optional[Union[int, float]] = None,
) -> Optional[_Timestamp]:
    if schedule_time and in_seconds is not None:
        raise ValueError("Provide either schedule_time or in_seconds, not both")

    if schedule_time is not None:
        return _to_timestamp(schedule_time)

    if in_seconds is not None:
        try:
            delta = float(in_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("in_seconds must be numeric") from exc
        if delta < 0:
            raise ValueError("in_seconds must be non-negative")
        schedule_dt = datetime.now(timezone.utc) + timedelta(seconds=delta)
        return _to_timestamp(schedule_dt)

    return None


def _merge_headers(
    headers: Optional[Mapping[str, str]],
    default_content_type: Optional[str],
) -> Optional[Dict[str, str]]:
    if headers:
        merged: MutableMapping[str, str] = dict(headers)
    else:
        merged = {}

    if default_content_type and not any(k.lower() == "content-type" for k in merged):
        merged["Content-Type"] = default_content_type

    return dict(merged) if merged else None


def create_http_task(
    *,
    parent: str,
    url: str,
    payload: Any = None,
    http_method: Union[str, Any] = "POST",
    headers: Optional[Mapping[str, str]] = None,
    schedule_time: Optional[datetime] = None,
    in_seconds: Optional[Union[int, float]] = None,
) -> Dict[str, Any]:
    """Build a request dictionary for ``CloudTasksClient.create_task``.

    Parameters mirror the public surface of ``google.cloud.tasks_v2.CloudTasksClient``
    but the function remains dependency free to keep the exercises lightweight.
    """

    if not parent or not isinstance(parent, str):
        raise ValueError("parent must be a non-empty string queue path")
    if not url or not isinstance(url, str):
        raise ValueError("url must be a non-empty string")

    method = _normalise_method(http_method)

    body_bytes, default_content_type = _encode_payload(payload)
    merged_headers = _merge_headers(headers, default_content_type)

    http_request: Dict[str, Any] = {
        "http_method": method,
        "url": url,
    }
    if merged_headers:
        http_request["headers"] = merged_headers
    if body_bytes is not None:
        http_request["body"] = body_bytes

    task: Dict[str, Any] = {"http_request": http_request}

    timestamp = _resolve_schedule(schedule_time=schedule_time, in_seconds=in_seconds)
    if timestamp is not None:
        task["schedule_time"] = timestamp.to_dict()

    return {"parent": parent, "task": task}
