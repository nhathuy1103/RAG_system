"""Authentication schemas exposed at the HTTP boundary."""

from pydantic import BaseModel


class CurrentUser(BaseModel):
    """Identity extracted from a verified Supabase access token."""

    id: str
    email: str | None = None
    role: str | None = None
    # App role (user/admin), distinct from the Postgres `role` above.
    user_role: str | None = None


class SupabaseUserResponse(BaseModel):
    """Safe diagnostic response for the current authenticated user."""

    user_id: str
    email: str | None = None
    role: str | None = None
