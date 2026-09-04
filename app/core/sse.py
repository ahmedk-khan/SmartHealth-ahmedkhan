"""Shared Server-Sent Events helpers for AI streaming endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any, Literal

from fastapi.responses import StreamingResponse

from app.core.exceptions import AppError, format_app_error

logger = logging.getLogger(__name__)

_SSE_FALLBACKS: dict[str, dict[str, str]] = {
    "assistant": {
        "type": "ai_error",
        "message": "The AI assistant is temporarily unavailable. Please try again later.",
        "code": "AI_PIPELINE_UNAVAILABLE",
    },
    "generation": {
        "type": "ai_error",
        "message": "Content generation is temporarily unavailable. Please try again later.",
        "code": "AI_GENERATION_FAILED",
    },
}

# Backward-compatible constants
AI_ASSISTANT_UNAVAILABLE = _SSE_FALLBACKS["assistant"]
AI_GENERATION_UNAVAILABLE = _SSE_FALLBACKS["generation"]


def sse_stream_error(
    exc: BaseException,
    *,
    domain: Literal["assistant", "generation"] = "generation",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Map stream failures to the standard REST error object."""
    if isinstance(exc, AppError):
        return format_app_error(exc, request_id=request_id)["error"]
    logger.exception("Unexpected error in %s stream", domain, exc_info=exc)
    payload = dict(_SSE_FALLBACKS[domain])
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def assistant_stream_error(exc: BaseException, request_id: str | None = None) -> dict[str, Any]:
    return sse_stream_error(exc, domain="assistant", request_id=request_id)


def generation_stream_error(exc: BaseException, request_id: str | None = None) -> dict[str, Any]:
    return sse_stream_error(exc, domain="generation", request_id=request_id)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse_event(event: str, data: Any) -> str:
    """Format a single SSE frame with JSON-serialized data."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def error_payload(exc: BaseException, request_id: str | None = None) -> dict[str, Any]:
    """Build an error object aligned with the REST API error envelope."""
    return generation_stream_error(exc, request_id=request_id)


def sse_error_events(exc: BaseException, request_id: str | None = None) -> list[str]:
    """Return terminal SSE frames for a failed AI stream."""
    err = generation_stream_error(exc, request_id=request_id)
    return [
        format_sse_event("error", {"error": err}),
        format_sse_event("done", {"ok": False, "error": err}),
    ]


def iter_text_chunks(text: str, chunk_size: int = 24) -> Iterator[str]:
    """Yield fixed-size chunks that rejoin into the original text."""
    if not text:
        return
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


def stream_text_as_text_events(text: str, *, chunk_size: int = 24) -> Iterator[str]:
    """Stream human-readable text as `text` SSE events for progressive clients."""
    for chunk in iter_text_chunks(text, chunk_size=chunk_size):
        yield format_sse_event("text", {"token": chunk})


def stream_json_as_text_events(payload: dict[str, Any], *, chunk_size: int = 24) -> Iterator[str]:
    """Stream a JSON object as `text` SSE events (legacy; prefer stream_text_as_text_events)."""
    serialized = json.dumps(payload, sort_keys=True)
    yield from stream_text_as_text_events(serialized, chunk_size=chunk_size)


def build_generation_done_payload(
    *,
    content: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized terminal SSE payload for generation endpoints."""
    payload: dict[str, Any] = {"ok": True}
    if content is not None:
        payload["content"] = content
    if report is not None:
        payload["report"] = report
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def ai_streaming_response(events: AsyncIterator[str]) -> StreamingResponse:
    """Return a StreamingResponse configured for AI SSE consumers."""
    return StreamingResponse(events, media_type="text/event-stream", headers=SSE_HEADERS)


async def stream_generation_payload(
    *,
    stream_text: str,
    content: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    report: dict[str, Any] | None = None,
    text_chunk_size: int | None = None,
) -> AsyncIterator[str]:
    """Emit one generation sequence, optionally as one complete text event."""
    chunk_size = text_chunk_size or 24
    for event in stream_text_as_text_events(stream_text, chunk_size=chunk_size):
        yield event
    yield format_sse_event("content", content)
    if metadata is not None:
        yield format_sse_event("metadata", metadata)
    if report is not None:
        yield format_sse_event("report", report)
    if citations is not None:
        yield format_sse_event("citations", citations)
    yield format_sse_event(
        "done",
        build_generation_done_payload(content=content if report is None else None, report=report, metadata=metadata),
    )
