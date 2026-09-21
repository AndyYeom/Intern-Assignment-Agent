"""Disk cache for GitHub API responses, keyed by request URL.

Two jobs:
  * make `build` re-runs free, so the schema can change without re-fetching
  * store ETags, because a 304 response does not count against the rate limit
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from generator.config import CACHE_DIR


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]


class ResponseCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or CACHE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        self.revalidated = 0

    def _path(self, url: str) -> Path:
        return self.root / f"{_key(url)}.json"

    def get(self, url: str) -> dict[str, Any] | None:
        path = self._path(url)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def read(self, url: str, max_age: float | None = None) -> Any | None:
        """Return the cached payload if present and fresh enough."""
        entry = self.get(url)
        if entry is None:
            return None
        if max_age is not None and time.time() - entry.get("fetched_at", 0) > max_age:
            return None
        self.hits += 1
        return entry.get("payload")

    def write(self, url: str, payload: Any, etag: str | None = None) -> None:
        entry = {
            "url": url,
            "etag": etag,
            "fetched_at": time.time(),
            "payload": payload,
        }
        tmp = self._path(url).with_suffix(".tmp")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        tmp.replace(self._path(url))

    def etag(self, url: str) -> str | None:
        entry = self.get(url)
        return entry.get("etag") if entry else None

    def touch(self, url: str) -> Any | None:
        """Mark a cached entry as re-validated (HTTP 304) and return its payload."""
        entry = self.get(url)
        if entry is None:
            return None
        entry["fetched_at"] = time.time()
        self._path(url).write_text(json.dumps(entry), encoding="utf-8")
        self.revalidated += 1
        return entry.get("payload")

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "revalidated": self.revalidated}
