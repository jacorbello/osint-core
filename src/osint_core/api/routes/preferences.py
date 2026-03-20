"""User preference and saved search API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.user_preference import UserPreference
from osint_core.schemas.preference import (
    PreferenceResponse,
    PreferenceUpdateRequest,
    SavedSearchRequest,
    SavedSearchResponse,
)

router = APIRouter(prefix="/api/v1", tags=["preferences"])


async def _get_or_create_preference(
    db: AsyncSession, user_sub: str
) -> UserPreference:
    """Return the preference row for this user, creating one if absent.

    Handles the race condition where two concurrent requests both try to
    create the row: on IntegrityError we roll back and re-select.
    """
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_sub == user_sub)
    )
    pref = result.scalar_one_or_none()
    if pref is not None:
        return pref

    try:
        pref = UserPreference(user_sub=user_sub)
        db.add(pref)
        await db.flush()
        await db.refresh(pref)
        return pref
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(UserPreference).where(UserPreference.user_sub == user_sub)
        )
        pref = result.scalar_one()
        return pref


# ── Preferences CRUD ────────────────────────────────────────────────

@router.get(
    "/preferences",
    response_model=PreferenceResponse,
    operation_id="getPreferences",
    responses=problem_response_docs(401),
)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PreferenceResponse:
    """Return the authenticated user's preferences."""
    pref = await _get_or_create_preference(db, current_user.sub)
    await db.commit()
    return PreferenceResponse.model_validate(pref)


@router.put(
    "/preferences",
    response_model=PreferenceResponse,
    operation_id="updatePreferences",
    responses=problem_response_docs(401, 422),
)
async def update_preferences(
    body: PreferenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PreferenceResponse:
    """Update the authenticated user's preferences."""
    pref = await _get_or_create_preference(db, current_user.sub)
    if body.notification_prefs is not None:
        pref.notification_prefs = body.notification_prefs
    if body.timezone is not None:
        pref.timezone = body.timezone
    await db.commit()
    await db.refresh(pref)
    return PreferenceResponse.model_validate(pref)


# ── Saved Searches CRUD ─────────────────────────────────────────────

@router.post(
    "/saved-searches",
    response_model=SavedSearchResponse,
    status_code=201,
    operation_id="createSavedSearch",
    responses=problem_response_docs(401, 422),
)
async def create_saved_search(
    body: SavedSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> SavedSearchResponse:
    """Create a new saved search for the authenticated user."""
    pref = await _get_or_create_preference(db, current_user.sub)
    search_entry = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "query": body.query,
        "filters": body.filters,
        "alert_enabled": body.alert_enabled,
        "created_at": datetime.now(UTC).isoformat(),
    }
    # JSONB mutation requires reassignment for SQLAlchemy change detection.
    pref.saved_searches = [*pref.saved_searches, search_entry]
    await db.commit()
    await db.refresh(pref)
    return SavedSearchResponse(**search_entry)


@router.get(
    "/saved-searches",
    response_model=list[SavedSearchResponse],
    operation_id="listSavedSearches",
    responses=problem_response_docs(401),
)
async def list_saved_searches(
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> list[SavedSearchResponse]:
    """List all saved searches for the authenticated user."""
    pref = await _get_or_create_preference(db, current_user.sub)
    await db.commit()
    return [SavedSearchResponse(**s) for s in pref.saved_searches]


@router.delete(
    "/saved-searches/{search_id}",
    status_code=204,
    operation_id="deleteSavedSearch",
    responses=problem_response_docs(401, 404),
)
async def delete_saved_search(
    search_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Response:
    """Delete a saved search by ID."""
    pref = await _get_or_create_preference(db, current_user.sub)
    original_count = len(pref.saved_searches)
    pref.saved_searches = [
        s for s in pref.saved_searches if s.get("id") != search_id
    ]
    if len(pref.saved_searches) == original_count:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Saved search not found",
        )
    await db.commit()
    return Response(status_code=204)
