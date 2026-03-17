"""Shared helpers for direct route tests."""

from __future__ import annotations

import asyncio

from starlette.requests import Request

from osint_core.api.middleware.auth import UserInfo


def run_async(awaitable):
    """Run an async route or dependency in a sync test."""
    return asyncio.run(awaitable)


def make_request(path: str, method: str = "GET", body: bytes = b"") -> Request:
    """Construct a minimal Starlette request for direct route tests."""

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        },
        receive=receive,
    )


def make_user() -> UserInfo:
    """Return a consistent authenticated user for route tests."""
    return UserInfo(sub="u-1", username="admin", roles=["admin"])
