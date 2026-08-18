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
    assert "_combined_dashboard_with_update_button_bytes" in content
    assert 'self.hass.config.path("kems_master_dashboard.yaml")' in content
    assert "installed.read_bytes()" in content


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


def test_release_discovery_rejects_leading_v_aliases_and_orders_versions() -> None:
    """A newer semantic KEMS bundle must not be masked by a leading-v alias."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert "_is_leading_v_alias(release_tag)" in content
    assert "base.version_relation(version, version) != 0" in content
    assert "base.version_relation(candidate[0], selected_version)" in content
    assert "if relation == 1" in content


def test_updates_dashboard_has_direct_check_for_updates_button() -> None:
    """The managed Updates view must expose the KEMS update-check action directly."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert '"        name: Check for updates\\n"' in content
    assert '"          action: perform-action\\n"' in content
    assert '"          perform_action: kems.check_for_updates\\n"' in content
    assert "await _async_sync_update_dashboard(hass)" in content
