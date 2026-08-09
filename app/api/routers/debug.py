"""Development-only diagnostic routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_current_user
from app.api.schemas.auth import CurrentUser, SupabaseUserResponse

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/supabase-user", response_model=SupabaseUserResponse)
async def read_supabase_user(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SupabaseUserResponse:
    """Return safe claims from a verified Supabase access token."""
    return SupabaseUserResponse(
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role,
    )
