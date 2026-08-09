"""Port for issuing short-lived links to private source files."""

from typing import Protocol


class SourceSigningError(RuntimeError):
    pass


class SourceUrlSigner(Protocol):
    async def sign(self, bucket_name: str, object_path: str, *, expires_in: int) -> str: ...
