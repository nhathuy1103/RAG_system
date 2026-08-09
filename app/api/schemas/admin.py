"""Admin dashboard schemas exposed at the HTTP boundary."""

from datetime import date, datetime

from pydantic import BaseModel


class AdminUserCountResponse(BaseModel):
    total_users: int


class AdminAuthEventDay(BaseModel):
    day: date
    signups: int
    logins: int
    logouts: int


class AdminAuthEventsResponse(BaseModel):
    days: list[AdminAuthEventDay]


class AdminAuditLogEntry(BaseModel):
    created_at: datetime
    action: str | None = None
    email: str | None = None


class AdminAuditLogResponse(BaseModel):
    entries: list[AdminAuditLogEntry]
