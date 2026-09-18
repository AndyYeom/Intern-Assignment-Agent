"""Rate-limit-aware, cache-backed GitHub REST client.

Works unauthenticated (60 req/hour) but is roughly 80x faster with a token in
GITHUB_TOKEN. Only public endpoints are used either way; a token with no scopes
is sufficient and is treated purely as a rate-limit key.
"""
from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from typing import Any, Self

import httpx

from generator.config import API_ROOT, USER_AGENT, github_token
from generator.github.cache import ResponseCache


class RateLimited(RuntimeError):
    pass


class NotFound(RuntimeError):
    """The resource is genuinely absent: 404, or an empty repository."""


class Unavailable(NotFound):
    """The resource exists but will not be served: blocked, forbidden or unprocessable.

    A subclass of NotFound on purpose - callers treat it as absent - but distinct
    from RateLimited, so one blocked repo can never abort a whole collection run.
    """


# Cached in place of a payload for a 404, so a known-missing resource is not
# re-requested on every run. A plain None would read as a cache miss.
_NOT_FOUND = {"__not_found__": True}


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        cache: ResponseCache | None = None,
        *,
        offline: bool = False,
        wait_on_limit: bool = True,
        max_wait: float = 3900.0,
    ) -> None:
        self.token = token if token is not None else github_token()
        self.cache = cache or ResponseCache()
        self.offline = offline
        self.wait_on_limit = wait_on_limit
        self.max_wait = max_wait
        self.remaining: int | None = None
        self.reset_at: float | None = None
        self.request_count = 0

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._http = httpx.Client(headers=headers, timeout=30.0, follow_redirects=True)

    # -- plumbing ---------------------------------------------------------

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _absorb_limits(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            self.remaining = int(remaining)
        if reset is not None:
            self.reset_at = float(reset)

    def _wait_for_reset(self) -> None:
        if not self.reset_at:
            time.sleep(60)
            return
        delay = max(0.0, self.reset_at - time.time()) + 2
        if delay > self.max_wait:
            raise RateLimited(
                f"rate limit resets in {delay:.0f}s, longer than max_wait={self.max_wait:.0f}s"
            )
        print(f"  [rate limit] sleeping {delay:.0f}s until reset", flush=True)
        time.sleep(delay)

    # -- requests ---------------------------------------------------------

    def get(self, path: str, *, params: dict[str, Any] | None = None, max_age: float | None = None) -> Any:
        """GET a path or absolute URL, using the cache and conditional requests."""
        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        if params:
            url = str(httpx.URL(url).copy_merge_params(params))

        cached = self.cache.read(url, max_age=max_age)
        if cached == _NOT_FOUND:
            raise NotFound(url)
        if cached is not None:
            return cached
        if self.offline:
            raise NotFound(f"offline and not cached: {url}")

        headers: dict[str, str] = {}
        etag = self.cache.etag(url)
        if etag:
            headers["If-None-Match"] = etag

        for attempt in range(6):
            if self.remaining is not None and self.remaining <= 0:
                if not self.wait_on_limit:
                    raise RateLimited("rate limit exhausted")
                self._wait_for_reset()
                self.remaining = None

            response = self._http.get(url, headers=headers)
            self.request_count += 1
            self._absorb_limits(response)

            if response.status_code == 304:
                payload = self.cache.touch(url)
                if payload is not None:
                    return payload
                headers.pop("If-None-Match", None)
                continue

            if response.status_code == 200:
                payload = response.json()
                self.cache.misses += 1
                self.cache.write(url, payload, etag=response.headers.get("ETag"))
                return payload

            if response.status_code == 204:
                # Empty repository: no commits, no contributors.
                self.cache.misses += 1
                self.cache.write(url, [], etag=None)
                return []

            if response.status_code == 404:
                self.cache.write(url, _NOT_FOUND, etag=None)
                raise NotFound(url)

            if response.status_code == 409:
                # "Git Repository is empty": no commits, no tree.
                self.cache.write(url, [], etag=None)
                return []

            if response.status_code in (451, 422):
                raise Unavailable(f"{response.status_code}: {url}")

            if response.status_code in (403, 429):
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    time.sleep(min(float(retry_after) + 1, self.max_wait))
                    continue
                if self.remaining == 0:
                    if not self.wait_on_limit:
                        raise RateLimited("rate limit exhausted")
                    self._wait_for_reset()
                    continue
                if "rate limit" in response.text.lower():
                    # Secondary (abuse) limit without a Retry-After header.
                    time.sleep(2 ** attempt)
                    continue
                # Quota remains and it is not a limit: access is simply refused
                # (blocked repo, history too large, token scope). Not retryable.
                raise Unavailable(f"403: {url}")

            if 500 <= response.status_code < 600:
                time.sleep(2 ** attempt)
                continue

            response.raise_for_status()

        raise RateLimited(f"gave up after retries: {url}")

    def paginate(self, path: str, *, params: dict[str, Any] | None = None, max_pages: int = 5) -> Iterator[Any]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        for page in range(1, max_pages + 1):
            params["page"] = page
            try:
                batch = self.get(path, params=params)
            except NotFound:
                return
            if not batch:
                return
            yield from batch
            if len(batch) < params["per_page"]:
                return

    # -- convenience ------------------------------------------------------

    def file_text(self, owner: str, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None:
        """Fetch a single file's decoded text, or None if missing/too big/binary."""
        try:
            payload = self.get(f"/repos/{owner}/{repo}/contents/{path}")
        except NotFound:
            return None
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            return None
        if payload.get("size", 0) > max_bytes:
            return None
        try:
            return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
        except (KeyError, ValueError):
            return None

    def budget_note(self) -> str:
        limit = "5000/hr (token)" if self.authenticated else "60/hr (unauthenticated)"
        remaining = "unknown" if self.remaining is None else str(self.remaining)
        return f"{limit}, remaining={remaining}, requests this run={self.request_count}"
