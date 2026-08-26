"""Regression coverage for the Alpha8.27 managed-dashboard entity fix."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"


def _load_pipeline_module():
    """Load the standalone pipeline module without importing the KEMS package."""
    spec = importlib.util.spec_from_file_location(
        "kems_dashboard_pipeline_alpha827", PIPELINE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_managed_dashboard_uses_registered_battery_charged_entity() -> None:
    """The rendered customer dashboard must not point at the old typo entity."""
    source = (ROOT / "dashboards" / "kems_master_dashboard.yaml").read_bytes()
    rendered = _load_pipeline_module()._finalise_dashboard_bytes(source).decode("utf-8")

    assert "sensor.kems_simulated_battery_charged_today" in rendered
    assert "sensor.kems_simulated_battery_charge_today" not in rendered


def test_alpha827_version_and_release_scope() -> None:
    """Alpha8.27 remains present in successor core/dashboard releases."""
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    version = manifest["version"]
    prefix = "0.8.0-alpha8."
    assert version.startswith(prefix)
    assert int(version.removeprefix(prefix)) >= 27
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
