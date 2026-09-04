import json

import pytest

from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.core.sse import (
    build_generation_done_payload,
    error_payload,
    format_sse_event,
    generation_stream_error,
    sse_error_events,
    stream_json_as_text_events,
    stream_text_as_text_events,
)


def test_format_sse_event_serializes_json():
    frame = format_sse_event("text", {"token": "hello"})
    assert frame == 'event: text\ndata: {"token": "hello"}\n\n'


def test_error_payload_maps_app_error():
    err = error_payload(NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND"), request_id="req-1")
    assert err["type"] == "not_found"
    assert err["code"] == "APPOINTMENT_NOT_FOUND"
    assert err["request_id"] == "req-1"


def test_sse_error_events_include_error_and_terminal_done():
    frames = sse_error_events(ForbiddenError("Denied"), request_id="req-2")
    assert len(frames) == 2
    assert frames[0].startswith("event: error\n")
    assert '"ok": false' in frames[1].lower()


def test_generation_stream_error_maps_unexpected_to_ai_generation_failed():
    err = generation_stream_error(RuntimeError("provider exploded"), request_id="req-3")
    assert err["type"] == "ai_error"
    assert err["code"] == "AI_GENERATION_FAILED"
    assert err["request_id"] == "req-3"


def test_build_generation_done_payload_includes_structured_fields():
    payload = build_generation_done_payload(
        content={"appointment_id": 1, "summary": "Confirmed"},
        metadata={"id": 9, "type": "summary"},
    )
    assert payload == {
        "ok": True,
        "content": {"appointment_id": 1, "summary": "Confirmed"},
        "metadata": {"id": 9, "type": "summary"},
    }


def test_stream_text_as_text_events_rejoin_to_plain_text():
    text = "Your appointment is confirmed."
    chunks = [frame for frame in stream_text_as_text_events(text)]
    assert chunks
    rebuilt = ""
    for frame in chunks:
        data = json.loads(frame.split("data: ", 1)[1])
        rebuilt += data["token"]
    assert rebuilt == text


def test_stream_json_as_text_events_rejoin_to_json():
    payload = {"appointment_id": 1, "subject": "Follow up"}
    chunks = [frame for frame in stream_json_as_text_events(payload)]
    assert chunks
    assert all(frame.startswith("event: text\n") for frame in chunks)
    joined = "".join(
        frame.split("data: ", 1)[1].strip()
        for frame in chunks
    )
    # Each data line is JSON with a token field
    import json

    rebuilt = ""
    for frame in chunks:
        data = json.loads(frame.split("data: ", 1)[1])
        rebuilt += data["token"]
    assert json.loads(rebuilt) == payload
