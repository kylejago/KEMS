"""Coordinated alpha9.198 release: two approved reporting/updater fixes only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
RELEASE = ROOT / "release" / "kems-bundle.template.json"


def test_release_version_bundle_and_optional_component_versions_are_pinned() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(RELEASE.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.9.0-alpha9.200"
    assert bundle["bundle"] == "__RELEASE_VERSION__"
    assert bundle["components"]["kems_core"]["version"] == "__RELEASE_VERSION__"
    assert bundle["components"]["dashboard"]["version"] == "__RELEASE_VERSION__"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.4"
    assert bundle["components"]["pi_agent"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["public_web"]["version"] == "0.9.0-alpha9-public.0"
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False


def test_reason_explicitly_guards_original_safety_and_provenance() -> None:
    bundle = json.loads(RELEASE.read_text(encoding="utf-8"))
    reason = bundle["maintenance"]["reason"]
    assert reason.startswith("Alpha9.200:")
    for statement in (
        "all three original",
        "identical Home Assistant sensor state+complete-attribute writes",
        "sibling GitHub manifest/checksum download",
        "SHA-256",
        "7 kW DNO",
        "15% deliberate-export reserve",
        "10% home floor/12% recovery",
        "Happy Hour/Power Down",
        "06:00-06:30 safe-first",
        "Prior Alpha9.197:",
    ):
        assert statement in reason


@pytest.mark.parametrize(
    "filename",
    [
        "agile_flow_presentation.py",
        "agile_canonical_flow_accounting.py",
        "agile_live_solar_soc_continuity.py",
    ],
)
def test_three_live_publications_remain_synchronous_and_flag_scoped(
    filename: str,
) -> None:
    source = (KEMS / filename).read_text(encoding="utf-8")
    assert source.count("self._publish(self._state)") >= 1
    assert 'self, "_kems_suppress_identical_base_publication", False' in source
    assert "self._kems_suppress_identical_base_publication = True" in source
    assert "finally:" in source
    assert (
        "self._kems_suppress_identical_base_publication = previous_identical_guard"
        in source
    )
    assert "_kems_defer_flow_live_update_publish" not in source
    assert "_kems_defer_canonical_live_update_publish" not in source


def test_shared_fail_closed_download_helper_is_used_by_both_update_paths() -> None:
    core = (KEMS / "kems_core" / "github_release_assets.py").read_text(encoding="utf-8")
    assert "async def download_release_asset_pair(" in core
    assert "task.cancel()" in core
    assert "return_exceptions=True" in core
    for filename in ("update_orchestrator.py", "update_orchestrator_reliable.py"):
        source = (KEMS / filename).read_text(encoding="utf-8")
        assert "await download_release_asset_pair(" in source
        assert "SHA-256 verification failed" in source


def test_maintenance_and_hardware_safety_gates_are_not_relaxed() -> None:
    guard = (KEMS / "update_maintenance_guard.py").read_text(encoding="utf-8")
    update = (KEMS / "update_orchestrator.py").read_text(encoding="utf-8")
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    assert "maintenance_energy_blockers(" in guard
    assert "self._energy_maintenance_blockers()" in update
    assert "self._defer_for_energy_activity(blockers)" in update
    assert "guard_paid_agile_physical_export(" in coordinator
    assert "self._foxess_control.async_update(" in coordinator
