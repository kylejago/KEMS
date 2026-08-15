"""Tests for the HACS-installed managed KEMS dashboard."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def test_packaged_master_dashboard_matches_repository_source() -> None:
    """HACS must receive the same master dashboard that the repo documents."""
    assert PACKAGED.exists()
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()


def test_managed_master_dashboard_is_valid_builtin_yaml() -> None:
    """The managed dashboard should parse and keep the expected master views."""
    content = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert content["title"] == "KEMS Master Dashboard"
    paths = {view["path"] for view in content["views"]}
    assert {
        "overview",
        "live-energy",
        "simulation",
        "forecast",
        "full-kems-forecast",
        "commissioning",
        "compare",
        "battery-solar",
        "tariff-ev",
        "power-down",
        "control-eps",
        "finance-history",
        "learning-health",
        "gas",
        "all-entities",
    } <= paths


def test_full_kems_forecast_view_exposes_operating_detail() -> None:
    """The dedicated forecast strategy view should expose plan, flow and audit data."""
    content = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    view = next(
        item for item in content["views"] if item["path"] == "full-kems-forecast"
    )
    rendered = str(view)
    assert "sensor.kems_full_kems_forecast_status" in rendered
    assert "sensor.kems_compare_full_kems_forecast_cost_today" in rendered
    assert "Current Full KEMS Forecast power routing" in rendered
    assert "Recharge & reserve decision" in rendered
    assert "Hourly fused solar / weather outlook" in rendered
    assert "Forecast protection audit inside the scenario" in rendered
    assert "Complete Full KEMS Forecast scenario attributes" in rendered


def test_kems_setup_syncs_managed_dashboard() -> None:
    """Integration startup must refresh its managed dashboard in /config."""
    setup = (ROOT / "custom_components" / "kems" / "__init__.py").read_text(
        encoding="utf-8"
    )
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "await async_sync_managed_dashboard(hass)" in setup
    assert 'MANAGED_DASHBOARD_FILENAME = "kems_master_dashboard.yaml"' in sync
    assert "hass.config.path(MANAGED_DASHBOARD_FILENAME)" in sync
    assert "os.replace(temporary, target)" in sync
