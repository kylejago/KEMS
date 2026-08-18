"""Tests for the HACS-installed managed KEMS dashboards."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
AGILE_SOURCE = ROOT / "dashboards" / "kems_agile_smart_export_builtin.yaml"
AGILE_PACKAGED = (
    ROOT
    / "custom_components"
    / "kems"
    / "kems_agile_smart_export_dashboard.yaml"
)


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


def test_packaged_agile_dashboard_matches_repository_source() -> None:
    """HACS must receive the documented Agile Smart Export dashboard."""
    assert AGILE_PACKAGED.exists()
    assert AGILE_PACKAGED.read_bytes() == AGILE_SOURCE.read_bytes()


def test_agile_dashboard_is_builtin_and_has_required_views() -> None:
    """The managed Agile comparison must parse with all requested sections."""
    content = yaml.safe_load(AGILE_PACKAGED.read_text(encoding="utf-8"))
    assert content["title"] == "Full KEMS Forecast vs Agile Smart Export"
    paths = {view["path"] for view in content["views"]}
    assert {"overview", "price-plan", "history", "assumptions"} <= paths
    rendered = str(content)
    assert "sensor.kems_agile_export_rate_now" in rendered
    assert "sensor.kems_agile_price_data_quality" in rendered
    assert "sensor.kems_agile_smart_export_plan" in rendered
    assert "sensor.kems_agile_advantage_today" in rendered
    assert "sensor.kems_full_kems_forecast_vs_agile_winner_all_time" in rendered


def test_agile_dashboard_is_synced_to_home_assistant_config() -> None:
    """Startup must refresh the second managed dashboard as well as the master."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert (
        'AGILE_DASHBOARD_FILENAME = "kems_agile_smart_export_dashboard.yaml"'
        in sync
    )
    assert "hass.config.path(AGILE_DASHBOARD_FILENAME)" in sync
    assert "PACKAGED_AGILE_DASHBOARD_PATH" in sync


def test_kems_setup_syncs_managed_dashboard() -> None:
    """Integration startup must refresh its managed dashboards in /config."""
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
