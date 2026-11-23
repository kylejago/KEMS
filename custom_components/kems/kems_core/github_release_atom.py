"""Strict read-only fallback for public KEMS alpha release assets.

The normal GitHub REST asset API remains preferred. An unauthenticated Home
Assistant IP can receive HTTP 403/429 from the REST release index; GitHub's
public Atom release feed and published release download URLs provide a second
independent transport. This transport NEVER substitutes an unverified branch
file, trusts a third-party host, or bypasses the release bundle SHA-256 check.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from urllib.parse import quote, urlsplit
from typing import Any

from .github_release_assets import ASSET_LIMIT_BYTES, download_release_asset_pair

_ATOM_URL = "https://github.com/kylejago/KEMS/releases.atom"
_ATOM_LIMIT = 256 * 1024
_ALPHA_TAG = re.compile(
    r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"-alpha(?P<generation>[0-9]+)\.(?P<build>[0-9]+)"
)
_ALLOWED_ASSETS = frozenset({"kems-bundle.json", "kems-bundle.json.sha256"})
_ALLOWED_HOSTS = frozenset(
    {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
)


def select_public_alpha_tag(atom_bytes: bytes) -> str | None:
    """Select the highest canonical release, not arbitrary Atom text or links."""
    if not atom_bytes or len(atom_bytes) > _ATOM_LIMIT:
        raise ValueError("KEMS public release feed is empty or too large")
    try:
        root = ET.fromstring(atom_bytes)
    except ET.ParseError as error:
        raise ValueError("Invalid KEMS public release feed XML") from error

    namespaced = "{http://www.w3.org/2005/Atom}"
    feed_name = root.tag
    if feed_name not in {f"{namespaced}feed", "feed"}:
        raise ValueError("KEMS public release feed has an unexpected root")
    prefix = namespaced if feed_name.startswith("{") else ""
    matching: list[tuple[tuple[int, ...], str]] = []
    for entry in root.findall(f"{prefix}entry"):
        for link in entry.findall(f"{prefix}link"):
            if link.get("rel", "alternate") != "alternate":
                continue
            parsed = urlsplit(link.get("href", ""))
            if (
                parsed.scheme != "https"
                or parsed.hostname != "github.com"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                continue
            root_path = "/kylejago/KEMS/releases/tag/"
            if not parsed.path.startswith(root_path):
                continue
            tag = parsed.path[len(root_path):]
            match = _ALPHA_TAG.fullmatch(tag)
            if match is None:
                continue
            matching.append((tuple(int(value) for value in match.groups()), tag))
    return max(matching)[1] if matching else None


def public_release_asset_url(tag: str, filename: str) -> str:
    """Allow only the exact canonical KEMS release filenames and version tag."""
    if _ALPHA_TAG.fullmatch(tag) is None or filename not in _ALLOWED_ASSETS:
        raise ValueError("Refusing an untrusted KEMS public release asset")
    return (
        "https://github.com/kylejago/KEMS/releases/download/"
        f"{quote(tag, safe='')}/{filename}"
    )


async def fetch_public_alpha_release_pair(
    session: Any, *, user_agent: str
) -> tuple[str, bytes, bytes]:
    """Return published release bytes; the caller MUST validate SHA and version.

    The caller uses a dedicated aiohttp session with larger header limits for
    GitHub's browser-download CSP header. HTTP errors, HTML/login responses,
    untrusted redirects and oversize assets all fail closed.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/atom+xml"}
    async with session.get(_ATOM_URL, headers=headers, timeout=20) as response:
        if response.status != 200:
            raise ValueError(f"KEMS public release feed returned HTTP {response.status}")
        atom_bytes = await response.content.read(_ATOM_LIMIT + 1)
    tag = select_public_alpha_tag(atom_bytes)
    if tag is None:
        raise ValueError("No canonical KEMS alpha release in public feed")

    async def download(asset: Mapping[str, Any]) -> bytes:
        filename = str(asset["name"])
        url = public_release_asset_url(tag, filename)
        async with session.get(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/octet-stream",
            },
            timeout=25,
            allow_redirects=True,
        ) as response:
            final = urlsplit(str(response.url))
            if (
                response.status != 200
                or final.scheme != "https"
                or final.hostname not in _ALLOWED_HOSTS
            ):
                raise ValueError(
                    f"Untrusted KEMS public asset response: HTTP {response.status}"
                )
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "text/html" in content_type:
                raise ValueError("KEMS public asset returned HTML, not release bytes")
            payload = await response.content.read(ASSET_LIMIT_BYTES + 1)
            if not payload or len(payload) > ASSET_LIMIT_BYTES:
                raise ValueError("KEMS public release asset is empty or too large")
            return payload

    manifest, checksum = await download_release_asset_pair(
        download,
        {"name": "kems-bundle.json"},
        {"name": "kems-bundle.json.sha256"},
    )
    return tag, manifest, checksum
