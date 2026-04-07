"""Realtime transport and SSE helpers."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime

import redis.asyncio as aioredis
import redis.exceptions
import structlog

from osint_core.config import settings
from osint_core.schemas.ui import StreamEventPayload

logger = structlog.get_logger()

_EVENT_TOPICS = ("alert.updated", "lead.updated", "job.updated")
_HEARTBEAT_SECONDS = 15
_REDIS_CONNECT_TIMEOUT_SECONDS = 1.0
_REDIS_IO_TIMEOUT_SECONDS = 1.0
_REDIS_RETRY_COOLDOWN_SECONDS = 5.0
_redis_unavailable_until = 0.0


def _topic_channel(topic: str) -> str:
    return f"{settings.realtime_channel_prefix}:{topic}"


def _pattern_channel() -> str:
    return f"{settings.realtime_channel_prefix}:*"


def _to_sse_frame(topic: str, payload: StreamEventPayload) -> str:
    return f"event: {topic}\ndata: {payload.model_dump_json()}\n\n"


def _redis_client():
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_IO_TIMEOUT_SECONDS,
    )  # type: ignore[no-untyped-call]


class MemoryRealtimeTransport:
    """In-process pub/sub fallback for development or degraded operation."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                    yield frame
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def publish(self, topic: str, payload: StreamEventPayload) -> None:
        frame = _to_sse_frame(topic, payload)
        async with self._lock:
            subscribers = list(self._subscribers)

        for queue in subscribers:
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                continue


class RedisRealtimeTransport:
    """Redis pub/sub transport used for multi-instance fanout."""

    async def subscribe(self) -> AsyncIterator[str]:
        redis_client = _redis_client()
        pubsub = redis_client.pubsub()
        try:
            await pubsub.psubscribe(_pattern_channel())
            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=_HEARTBEAT_SECONDS,
                    )
                except (redis.exceptions.RedisError, OSError):
                    logger.warning("realtime_redis_subscribe_failed", exc_info=True)
                    break

                if message is None:
                    yield ": heartbeat\n\n"
                    continue

                raw_data = message.get("data")
                if not isinstance(raw_data, str):
                    continue
                try:
                    envelope = json.loads(raw_data)
                    topic = str(envelope["topic"])
                    payload = StreamEventPayload.model_validate(envelope["payload"])
                    yield _to_sse_frame(topic, payload)
                except (KeyError, TypeError, ValueError):
                    logger.warning("realtime_invalid_message", raw=raw_data[:200])
                    continue
        finally:
            with suppress(Exception):
                await pubsub.close()
            with suppress(Exception):
                await redis_client.aclose()

    async def publish(self, topic: str, payload: StreamEventPayload) -> None:
        redis_client = _redis_client()
        try:
            envelope = {
                "topic": topic,
                "payload": payload.model_dump(mode="json"),
            }
            await redis_client.publish(_topic_channel(topic), json.dumps(envelope))
        finally:
            with suppress(Exception):
                await redis_client.aclose()


_memory_transport = MemoryRealtimeTransport()
_redis_transport = RedisRealtimeTransport()


async def subscribe_events() -> AsyncIterator[str]:
    """Subscribe to stream frames, preferring Redis with memory fallback."""
    if settings.realtime_backend == "memory":
        async for frame in _memory_transport.subscribe():
            yield frame
        return

    try:
        async for frame in _redis_transport.subscribe():
            yield frame
    except (redis.exceptions.RedisError, OSError):
        logger.warning("realtime_subscribe_fallback_memory", exc_info=True)
        async for frame in _memory_transport.subscribe():
            yield frame


async def publish_event(
    *,
    event_type: str,
    resource: str,
    resource_id: str | uuid.UUID,
    payload: dict[str, object] | None = None,
) -> None:
    """Publish a normalized realtime event envelope."""
    event_payload = StreamEventPayload(
        type=event_type,
        resource=resource,
        id=str(resource_id),
        timestamp=datetime.now(UTC),
        payload=payload or {},
    )
    if event_type not in _EVENT_TOPICS:
        logger.warning("realtime_unknown_topic", event_type=event_type)

    if settings.realtime_backend == "memory":
        await _memory_transport.publish(event_type, event_payload)
        return

    global _redis_unavailable_until
    now = time.monotonic()
    if now < _redis_unavailable_until:
        await _memory_transport.publish(event_type, event_payload)
        return

    try:
        await _redis_transport.publish(event_type, event_payload)
    except (redis.exceptions.RedisError, OSError):
        _redis_unavailable_until = time.monotonic() + _REDIS_RETRY_COOLDOWN_SECONDS
        logger.warning("realtime_publish_fallback_memory", exc_info=True)
        await _memory_transport.publish(event_type, event_payload)
