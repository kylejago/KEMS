"""Successor regression for the managed-dashboard pipeline introduced in Alpha8.16."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
PIPELINE_PATH = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"
INIT_PATH = ROOT / "custom_components" / "kems" / "__init__.py"
MANIFEST_PATH = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE_PATH = ROOT / "release" / "kems-bundle.template.json"


def test_successor_pipeline_keeps_one_authoritative_dashboard_payload() -> None:
    """Alpha8.19 may replace composition, but sync and verification must still agree."""
    content = PIPELINE_PATH.read_text(encoding="utf-8")
    init = INIT_PATH.read_text(encoding="utf-8")

    assert "PACKAGED_DASHBOARD_PATH.read_bytes()" in content
    assert (
        "dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes" in content
    )
    assert "convergent._managed_dashboard_bytes = _fresh_dashboard_bytes" in content
    assert "dashboard_consolidation" not in content
    assert "improve_energy_bill_dashboard" not in content
    assert (
        init.index("install_energy_bill_dashboard_patch()")
        < init.index("install_dashboard_pipeline()")
        < init.index("await async_sync_managed_dashboard(hass)")
    )


def test_alpha816_safety_and_external_release_contract_survives_successors() -> None:
    """Dashboard rebuilds must not silently redeploy Web/panel or enable control."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    content = PIPELINE_PATH.read_text(encoding="utf-8")

    assert manifest["version"].startswith("0.8.0-alpha8.")
    assert int(manifest["version"].rsplit(".", 1)[-1]) >= 19
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.8"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.8"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.8"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "real_backend" not in content
    assert "commands_permitted" not in content
