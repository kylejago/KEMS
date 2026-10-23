"""Alpha9.129: safe GitHub REST release asset download for unattended updates."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from kems_core.github_release_assets import asset_api_url, download_release_asset

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


class _Response:
    def __init__(self, body: bytes, *, status: int = 200, media: str = "application/octet-stream") -> None:
        self.status = status
        self.headers = {"Content-Type": media}
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        return self.body


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.response


def _asset(body: bytes) -> dict:
    return {
        "id": 670363823,
        "size": len(body),
        "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
        "browser_download_url": "https://github.com/blocked-by-long-csp",
    }


def _download(session: _Session, asset: dict) -> bytes:
    return asyncio.run(
        download_release_asset(
            session, asset, repository="kylejago/KEMS",
            user_agent="KEMS-Home-Assistant-Update-Orchestrator",
        )
    )


def test_binary_download_via_github_rest_not_browser_page() -> None:
    body = b'{"bundle":"0.9.0-alpha9.129"}'
    session = _Session(_Response(body))
    assert _download(session, _asset(body)) == body
    assert session.calls == [(
        "https://api.github.com/repos/kylejago/KEMS/releases/assets/670363823",
        {
            "Accept": "application/octet-stream",
            "User-Agent": "KEMS-Home-Assistant-Update-Orchestrator",
        },
        15,
    )]


def test_metadata_json_fails_closed_with_no_browser_fallback() -> None:
    body = b'{"id":670363823,"name":"kems-bundle.json"}'
    session = _Session(_Response(body, media="application/json"))
    with pytest.raises(ValueError, match="metadata/HTML"):
        _download(session, _asset(body))
    assert len(session.calls) == 1


def test_bad_api_status_and_digest_block_install() -> None:
    body = b"valid bundle bytes"
    with pytest.raises(ValueError, match="HTTP 302"):
        _download(_Session(_Response(body, status=302)), _asset(body))
    asset = _asset(body)
    asset["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest disagrees"):
        _download(_Session(_Response(body)), asset)


def test_asset_id_repository_and_declared_size_restricted() -> None:
    body = b"valid bundle bytes"
    for bad_id in (None, 0, -1, True, "670363823"):
        with pytest.raises(ValueError, match="numeric ID"):
            _download(_Session(_Response(body)), {**_asset(body), "id": bad_id})
    with pytest.raises(ValueError, match="bounded manifest"):
        _download(
            _Session(_Response(body)),
            {**_asset(body), "size": 1024 * 1024 + 1},
        )
    with pytest.raises(ValueError, match="another release repository"):
        asset_api_url(_asset(body), repository="attacker/repo")


def test_unchanged_updater_gate_and_maintenance_contracts() -> None:
    base = (ROOT / "update_orchestrator.py").read_text()
    reliable = (ROOT / "update_orchestrator_reliable.py").read_text()
    guard = (ROOT / "update_maintenance_guard.py").read_text()
    for s in (base, reliable):
        assert "download_release_asset(" in s
        assert 'headers["User-Agent"]' in s
        assert 'asset.get("browser_download_url")' not in s
        assert "SHA-256 verification failed" in s
    assert "maintenance_energy_blockers(" in guard
    assert "self._energy_maintenance_blockers()" in base
    assert "await self._defer_for_energy_activity(blockers)" in base
    assert 'self.hass.services.async_call(' in base
