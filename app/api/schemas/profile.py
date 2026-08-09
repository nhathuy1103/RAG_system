"""Profile schemas exposed at the HTTP boundary."""

from datetime import datetime

from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    """The current user's app-owned profile row (public.profiles), enriched
    with email - which lives in auth.users, not profiles, so it's read from
    the caller's own JWT claims instead of a DB column (see get_profile in
    app/api/routers/profile.py)."""

    id: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    role: str
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Fields a user may edit about their own profile.

    `role` is deliberately not editable here - the profiles_update_own RLS
    policy (database/04_rls_policies.sql) also blocks changing it directly,
    this is just the matching guard at the API boundary.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    avatar_url: str | None = None
