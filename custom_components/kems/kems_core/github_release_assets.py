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

from aiohttp import ClientConnectionError
from collections.abc import Mapping
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
                            try:
                                rate_delay = float(response.headers.get("Retry-After", 0.6))
                            except (TypeError, ValueError, OverflowError):
                                rate_delay = 0.6
                            # Long rate limits defer to the scheduled check.
                            if not 0 <= rate_delay <= 3:
                                raise ValueError(
                                    "GitHub rate limit: defer to next update check"
                                )
                            delay = max(delay, rate_delay)
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
        except (TimeoutError, ConnectionError, ClientConnectionError):
            if attempt:
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
