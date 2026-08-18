"""Regression coverage for live coordinated-update reliability repairs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
RELIABLE = ROOT / "custom_components" / "kems" / "update_orchestrator_reliable.py"
INIT = ROOT / "custom_components" / "kems" / "__init__.py"


def test_kems_uses_reliable_orchestrator_setup() -> None:
    """Integration startup must instantiate the reliability-hardened orchestrator."""
    content = INIT.read_text(encoding="utf-8")
    assert (
        "from .update_orchestrator_reliable import async_setup_update_orchestrator"
        in content
    )


def test_reliable_orchestrator_waits_for_post_restart_bundle_before_success() -> None:
    """Startup must not verify a pending update before its release bundle reloads."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert "self.pending and self.latest_bundle is None" in content
    assert "await super().async_verify_pending(save=save)" in content


def test_reliable_orchestrator_verifies_the_combined_managed_dashboard() -> None:
    """Dashboard verification must include the Agile views appended at runtime."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert "_combined_master_dashboard_bytes" in content
    assert 'self.hass.config.path("kems_master_dashboard.yaml")' in content
    assert "installed.read_bytes() == _combined_master_dashboard_bytes()" in content


def test_reliable_orchestrator_clears_stale_failure_after_success() -> None:
    """A prior failure must not remain visible on a later completed transaction."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert 'if status != "failed"' in content
    assert 'payload["error"] = None' in content
    assert 'self.pending.pop("error", None)' in content


def test_reliable_orchestrator_uses_canonical_hacs_version() -> None:
    """HACS must receive the bundle target rather than a leading-v release alias."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert 'target = base._component_target(bundle, "kems_core")' in content
    assert 'release["tag"] = target' in content
