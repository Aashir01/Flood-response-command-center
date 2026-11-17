"""Shared HTTP call with retries for hosted providers. Secrets stay in headers; error messages
carry only the status code."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

import httpx

from stitch_voice.providers.base import CredentialsRejected, RateLimited, UpstreamFailed

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _retry_after(resp: httpx.Response, default: float) -> float:
    try:
        return min(10.0, max(0.0, float(resp.headers.get("retry-after", default))))
    except ValueError:
        return default


def post_with_retries(
    client: httpx.Client,
    vendor: str,
    url: str,
    *,
    params: Mapping[str, str],
    headers: Mapping[str, str],
    content: bytes,
    attempts: int = 3,
    timeout_s: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """POST with up to ``attempts`` tries for 429/5xx/transport errors (exponential backoff,
    ``Retry-After`` honoured, capped at 10 s). 401/403 raise ``CredentialsRejected``."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = client.post(
                url, params=params, headers=headers, content=content, timeout=timeout_s
            )
        except httpx.HTTPError as exc:  # timeouts and connection errors
            last = UpstreamFailed(f"{vendor} request failed ({type(exc).__name__})")
            if attempt + 1 < attempts:
                sleep(0.5 * 2**attempt)
            continue
        if resp.status_code in (401, 403):
            raise CredentialsRejected(f"{vendor} rejected the credentials ({resp.status_code})")
        if resp.status_code in RETRY_STATUS:
            last = (
                RateLimited(f"{vendor} rate limited the request (429)")
                if resp.status_code == 429
                else UpstreamFailed(f"{vendor} returned {resp.status_code}")
            )
            if attempt + 1 < attempts:
                sleep(_retry_after(resp, 0.5 * 2**attempt))
            continue
        if resp.status_code >= 400:
            raise UpstreamFailed(f"{vendor} returned {resp.status_code}")
        return resp
    assert last is not None
    raise last
