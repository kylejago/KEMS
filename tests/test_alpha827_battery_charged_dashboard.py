"""Regression coverage for the Alpha8.27 managed-dashboard entity fix."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.kems.dashboard_pipeline import _finalise_dashboard_bytes

ROOT = Path(__file__).resolve().parents[1]


def test_managed_dashboard_uses_registered_battery_charged_entity() -> None:
    """The rendered customer dashboard must not point at the old typo entity."""
    source = (ROOT / "dashboards" / "kems_master_dashboard.yaml").read_bytes()
    rendered = _finalise_dashboard_bytes(source).decode("utf-8")

    assert "sensor.kems_simulated_battery_charged_today" in rendered
    assert "sensor.kems_simulated_battery_charge_today" not in rendered


def test_alpha827_version_and_release_scope() -> None:
    """Alpha8.27 is a core/dashboard-only corrective release."""
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.27"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
