"""Alpha9.130 automated update canary: no changes to live energy control."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_canary_targets_only_update_version_and_preserves_energy_safety() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.151"
    reason = bundle["maintenance"]["reason"]
    assert reason.startswith("Alpha9.151:")
    assert "separate physical readback" in reason
    assert "Maintain all safety deferrals" in reason


def test_canary_preserves_github_verification_and_maintenance_deferral() -> None:
    base = (KEMS / "update_orchestrator.py").read_text()
    reliable = (KEMS / "update_orchestrator_reliable.py").read_text()
    transport = (KEMS / "kems_core" / "github_release_assets.py").read_text()
    assert "download_release_asset(" in base
    assert "download_release_asset(" in reliable
    assert "application/octet-stream" in transport
    assert "SHA-256 verification failed" in base
    assert "SHA-256 verification failed" in reliable
    assert "blockers = self._energy_maintenance_blockers()" in base
    assert "await self._defer_for_energy_activity(blockers)" in base
    assert "self._in_maintenance_window()" in base
