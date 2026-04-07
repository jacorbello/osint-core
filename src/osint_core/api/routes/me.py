"""Current-user identity route."""

from fastapi import APIRouter, Depends

from osint_core.api.deps import get_current_user
from osint_core.api.middleware.auth import UserInfo
from osint_core.config import settings
from osint_core.schemas.ui import MeResponse

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get(
    "/me",
    response_model=MeResponse,
    operation_id="getCurrentUser",
)
async def get_me(
    current_user: UserInfo = Depends(get_current_user),
) -> MeResponse:
    """Return the active API user identity."""
    return MeResponse(
        sub=current_user.sub,
        username=current_user.username,
        roles=current_user.roles,
        auth_disabled=settings.auth_disabled,
    )
