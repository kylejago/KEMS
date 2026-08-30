"""Regression coverage for Alpha8.17 coordinated-updater sequencing."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONVERGENT = ROOT / "custom_components" / "kems" / "update_orchestrator_convergent.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _verify_pending_body() -> str:
    content = CONVERGENT.read_text(encoding="utf-8")
    start = content.index("    async def async_verify_pending")
    end = content.index("    def _dashboard_current", start)
    return content[start:end]


def test_newer_pending_core_defers_dashboard_convergence() -> None:
    """A target newer than the running core must not fail dashboard convergence."""
    body = _verify_pending_body()

    running_at = body.index("running = base._installed_integration_version()")
    target_gate_at = body.index(
        "if target and not base._version_matches(running, target):"
    )
    defer_at = body.index(
        "Dashboard convergence starts only after the target core is active."
    )
    converge_at = body.index(
        "verification = await _async_converge_dashboard(self.hass, strict=True)"
    )

    assert running_at < target_gate_at < defer_at < converge_at
    assert "self._dashboard_expected_sha256 = None" in body
    assert "self._dashboard_installed_sha256 = None" in body
    assert "await self._async_save()" in body
    assert "self._write_legacy_states()" in body
    assert body.index("return", defer_at) < converge_at


def test_stale_older_pending_target_still_uses_proven_base_cleanup() -> None:
    """Running a newer core must retain the existing stale-target clearing path."""
    body = _verify_pending_body()

    assert "relation = base.version_relation(target, running)" in body
    assert "if relation is not None and relation < 0:" in body
    assert (
        "await base.KEMSUpdateOrchestrator.async_verify_pending(\n"
        "                        self, save=save\n"
        "                    )" in body
    )


def test_exact_target_still_requires_strict_dashboard_convergence() -> None:
    """An active target core must still require exact dashboard convergence."""
    body = _verify_pending_body()

    assert (
        "verification = await _async_converge_dashboard(self.hass, strict=True)" in body
    )
    assert "await self._fail_pending(str(error))" in body
    assert "self._remember_dashboard_verification(verification)" in body
    assert "base.KEMSUpdateOrchestrator.async_verify_pending(self, save=save)" in body


def test_alpha817_contract_survives_coordinated_successor_releases() -> None:
    """Successors must retain sequencing, scope, external pins, and safety."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    content = CONVERGENT.read_text(encoding="utf-8")

    assert manifest["version"].startswith("0.8.0-alpha8.")
    assert int(manifest["version"].rsplit(".", 1)[-1]) >= 17
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert "real_backend" not in content
    assert "commands_permitted" not in content
