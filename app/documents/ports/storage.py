"""Object-storage contracts for immutable document bytes."""

from typing import Protocol


class ObjectStorageError(RuntimeError):
    """Raised when document object storage cannot complete an operation."""


class DocumentObjectStorage(Protocol):
    """Storage operations required by document upload use cases."""

    async def upload(
        self,
        bucket: str,
        object_path: str,
        content: bytes,
        mime_type: str,
    ) -> None: ...

    async def delete(self, bucket: str, object_path: str) -> None: ...

    async def download(self, bucket: str, object_path: str) -> bytes: ...
