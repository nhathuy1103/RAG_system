from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    status_code: int


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.detail = ErrorDetail(
            code=code,
            message=message,
            status_code=status_code,
        )


__all__ = ["AppError", "ErrorDetail"]
