"""Realtime streaming API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from osint_core.api.deps import get_current_user
from osint_core.api.middleware.auth import UserInfo
from osint_core.api.realtime import subscribe_events

router = APIRouter(prefix="/api/v1", tags=["stream"])


@router.get(
    "/stream",
    operation_id="streamUpdates",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": (
                        "event: alert.updated\n"
                        'data: {"type":"alert.updated","resource":"alert","id":"..."}\n\n'
                    )
                }
            },
            "description": "SSE stream with heartbeat comments and update events",
        },
    },
)
async def stream_updates(
    current_user: UserInfo = Depends(get_current_user),
) -> StreamingResponse:
    """Open an SSE stream for realtime updates."""
    del current_user

    async def _event_stream():
        async for frame in subscribe_events():
            yield frame

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
