"""Keycloak OIDC JWT authentication middleware."""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel

from osint_core.config import settings

logger = structlog.get_logger()

# JWKS cache
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expiry: float = 0.0
_JWKS_CACHE_TTL = 300  # 5 minutes


class UserInfo(BaseModel):
    """Authenticated user information extracted from the JWT token."""

    sub: str
    username: str
    roles: list[str] = []


_DEFAULT_ADMIN = UserInfo(
    sub="dev-admin",
    username="admin",
    roles=["admin"],
)


async def _fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS from Keycloak, with caching."""
    global _jwks_cache, _jwks_cache_expiry

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_cache_expiry:
        return _jwks_cache

    jwks_url = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/certs"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_expiry = now + _JWKS_CACHE_TTL
        return _jwks_cache


def _extract_roles(payload: dict[str, Any]) -> list[str]:
    """Extract realm roles from the JWT payload."""
    realm_access = payload.get("realm_access", {})
    roles: list[str] = realm_access.get("roles", [])
    return roles


async def get_current_user(
    request: Request,
) -> UserInfo:
    """FastAPI dependency that extracts and validates the Bearer JWT token.

    When ``settings.auth_disabled`` is True (default for dev/test), returns a
    default admin user without checking any token.

    Health/metrics endpoints are exempt and should not use this dependency.
    """
    if settings.auth_disabled:
        return _DEFAULT_ADMIN

    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header (expected Bearer token)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        jwks = await _fetch_jwks()
        # Decode header to find the key id (kid)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find the matching key
        rsa_key: dict[str, Any] = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching signing key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        issuer = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.keycloak_client_id,
            issuer=issuer,
        )

        sub = payload.get("sub", "")
        username = payload.get("preferred_username", payload.get("sub", "unknown"))
        roles = _extract_roles(payload)

        return UserInfo(sub=sub, username=username, roles=roles)

    except JWTError as exc:
        logger.warning("jwt_validation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("jwks_fetch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to validate token (JWKS unavailable)",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_role(role: str) -> Callable[..., Coroutine[Any, Any, UserInfo]]:
    """Dependency factory that ensures the user has a specific role.

    Usage::

        @router.get("/admin-only")
        async def admin_endpoint(user: UserInfo = Depends(require_role("admin"))):
            ...
    """

    async def _check_role(
        user: UserInfo = Depends(get_current_user),
    ) -> UserInfo:
        if settings.auth_disabled:
            return user
        if role not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role '{role}' not found",
            )
        return user

    return _check_role
