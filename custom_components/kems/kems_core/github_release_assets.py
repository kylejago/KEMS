"""Read-only, authenticated-by-hash GitHub release asset transport.

Use GitHub's REST asset endpoint instead of the github.com browser download
page. That page's large CSP header exceeds aiohttp's default 8190-byte field
limit in Home Assistant. GitHub documents application/octet-stream on the REST
endpoint for a 200 binary body or 302 redirect to the binary CDN.

Never fall back to the browser HTML endpoint, silently accept API metadata as
an asset, or bypass the bundle SHA-256 and release-version checks.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any

ASSET_LIMIT_BYTES = 1024 * 1024
_HASH = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


def asset_api_url(asset: Mapping[str, Any], *, repository: str) -> str:
    """Derive a trusted, fixed-repository API endpoint from an asset ID."""
    if repository != "kylejago/KEMS":
        raise ValueError("KEMS updater refuses another release repository")
    asset_id = asset.get("id")
    if type(asset_id) is not int or asset_id <= 0:
        raise ValueError("GitHub release asset has no valid numeric ID")
    declared_size = asset.get("size")
    if declared_size is not None and (
        type(declared_size) is not int
        or declared_size < 1
        or declared_size > ASSET_LIMIT_BYTES
    ):
        raise ValueError("GitHub release asset size exceeds bounded manifest limit")
    return f"https://api.github.com/repos/{repository}/releases/assets/{asset_id}"


def _bounded_retry_after(header: Any) -> float:
    """Respect GitHub Retry-After seconds or HTTP-date without long sleeps.

    A delay beyond the single short retry allowance, an invalid header, or a
    timezone-less date must defer to the next scheduled check. This helper
    never moves the installation window or changes bundle verification.
    """
    if header is None:
        return 0.6
    numeric = True
    try:
        delay = float(header)
    except (TypeError, ValueError, OverflowError):
        numeric = False
        try:
            retry_at = parsedate_to_datetime(str(header))
            if retry_at.tzinfo is None:
                raise ValueError("GitHub Retry-After date has no timezone")
            delay = (retry_at - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("GitHub rate limit: defer to next update check") from error
    # HTTP-date values that just passed may retry once; negative numeric
    # seconds, NaN/inf, or long waits defer without another request.
    if not isfinite(delay) or delay > 3 or (numeric and delay < 0):
        raise ValueError("GitHub rate limit: defer to next update check")
    return max(0.6, delay)


async def download_release_asset(
    session: Any,
    asset: Mapping[str, Any],
    *,
    repository: str,
    user_agent: str,
) -> bytes:
    """Download a bounded GitHub asset; retry *only* transient transport loss.

    A failed signature, unexpected media type, wrong version or HTTP 4xx is
    never retried. Two attempts are enough to survive one short congestion
    event without repeatedly hammering GitHub overnight.
    """
    url = asset_api_url(asset, repository=repository)
    for attempt in range(2):
        try:
            async with session.get(
                url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": user_agent,
                },
                timeout=15,
            ) as response:
                if response.status in (429, 500, 502, 503, 504):
                    if attempt == 0:
                        delay = 0.6
                        if response.status == 429:
                            delay = _bounded_retry_after(
                                response.headers.get("Retry-After")
                            )
                        await asyncio.sleep(delay)
                        continue
                    raise ValueError(
                        "KEMS GitHub API asset download returned HTTP "
                        f"{response.status}"
                    )
                if response.status != 200:
                    raise ValueError(
                        "KEMS GitHub API asset download returned HTTP "
                        f"{response.status}"
                    )
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if "application/json" in content_type or "text/html" in content_type:
                    raise ValueError(
                        "GitHub returned asset metadata/HTML instead of a binary "
                        "release bundle; refusing unsafe fallback"
                    )
                payload = await response.read()
            break
        except Exception as error:
            # This pure core module also runs in the standalone test suite
            # without Home Assistant/aiohttp installed. Recognise aiohttp's
            # connection family without importing that optional dependency.
            transient = isinstance(error, (TimeoutError, ConnectionError)) or any(
                cls.__name__ == "ClientConnectionError"
                and cls.__module__ == "aiohttp.client_exceptions"
                for cls in type(error).__mro__
            )
            if not transient or attempt:
                raise
            await asyncio.sleep(0.6)
    if not payload or len(payload) > ASSET_LIMIT_BYTES:
        raise ValueError("GitHub release bundle asset was empty or too large")

    claimed_digest = asset.get("digest")
    if claimed_digest is not None:
        matched = _HASH.fullmatch(str(claimed_digest))
        if matched is None:
            raise ValueError("GitHub release asset digest has invalid format")
        if hashlib.sha256(payload).hexdigest().lower() != matched[1].lower():
            raise ValueError("GitHub release asset digest disagrees with bytes")
    return payload
