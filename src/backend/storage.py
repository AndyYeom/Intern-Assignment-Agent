"""Blob storage for applicant documents.

Only LocalStorage exists. It writes under STORAGE_ROOT on the container's
filesystem, which is NOT durable on ECS: a replaced task loses every upload.
Replace it with an S3-backed implementation of `Storage` before accepting real
applicant submissions. Callers only ever hold opaque storage keys, so that
swap is local to this module.
"""

import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO, Protocol


class Storage(Protocol):
    def save(self, data: bytes, *, prefix: str, suffix: str) -> str:
        """Store bytes and return an opaque key."""
        ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def as_local_file(self, key: str) -> AbstractContextManager[Path]:
        """Context manager yielding a local filesystem path for `key`.

        LocalStorage yields the real, already-local path. An S3-backed
        implementation would download the object to a temporary file here and
        clean it up on exit, so callers never assume a local filesystem.
        """
        ...


class LocalStorage:
    """Stores objects as files under `root`; keys are root-relative POSIX paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("storage key escapes the storage root")
        return path

    def save(self, data: bytes, *, prefix: str, suffix: str) -> str:
        key = f"{prefix.strip('/')}/{uuid.uuid4().hex}{suffix}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return key

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    @contextmanager
    def as_local_file(self, key: str) -> Iterator[Path]:
        yield self._path(key)
