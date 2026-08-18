"""Tests for the HACS-installed managed KEMS dashboards."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
AGILE_SOURCE = ROOT / "dashboards" / "kems_agile_smart_export_builtin.yaml"
AGILE_PACKAGED = (
    ROOT / "custom_components" / "kems" / "kems_agile_smart_export_dashboard.yaml"
)


def _merged_master_content() -> dict:
    """Mirror the runtime merge of Agile comparison views into the master."""
    master = PACKAGED.read_text(encoding="utf-8").rstrip()
    agile = AGILE_PACKAGED.read_text(encoding="utf-8")
    marker = "\nviews:\n"
    assert marker in agile
    agile_views = agile.split(marker, 1)[1].lstrip("\n")
    merged = f"{master}\n\n{agile_views}"
    return yaml.safe_load(merged)


def test_packaged_master_dashboard_matches_repository_source() -> None:
    """HACS must receive the same master dashboard base that the repo documents."""
    assert PACKAGED.exists()
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()


def test_managed_master_dashboard_is_valid_builtin_yaml() -> None:
    """The runtime master should parse and include normal plus Agile views."""
    content = _merged_master_content()
    assert content["title"] == "KEMS Master Dashboard"
    paths = {view["path"] for view in content["views"]}
    assert {
        "overview",
        "live-energy",
        "simulation",
        "forecast",
        "full-kems-forecast",
        "forecast-vs-agile",
        "agile-price-plan",
        "agile-history",
        "agile-assumptions",
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
    """HACS must receive the Agile view source used by the managed master."""
    assert AGILE_PACKAGED.exists()
    assert AGILE_PACKAGED.read_bytes() == AGILE_SOURCE.read_bytes()


def test_agile_dashboard_is_builtin_and_has_required_views() -> None:
    """The Agile comparison source must parse with all requested sections."""
    content = yaml.safe_load(AGILE_PACKAGED.read_text(encoding="utf-8"))
    assert content["title"] == "Full KEMS Forecast vs Agile Smart Export"
    paths = {view["path"] for view in content["views"]}
    assert {
        "forecast-vs-agile",
        "agile-price-plan",
        "agile-history",
        "agile-assumptions",
    } <= paths
    rendered = str(content)
    assert "sensor.kems_agile_export_rate_now" in rendered
    assert "sensor.kems_agile_price_data_quality" in rendered
    assert "sensor.kems_agile_smart_export_plan" in rendered
    assert "sensor.kems_agile_advantage_today" in rendered
    assert "sensor.kems_full_kems_forecast_vs_agile_winner_all_time" in rendered


def test_agile_dashboard_is_embedded_into_master_config() -> None:
    """Startup should merge Agile views into the one managed master dashboard."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "_combined_master_dashboard_bytes" in sync
    assert "PACKAGED_AGILE_DASHBOARD_PATH" in sync
    assert "hass.config.path(MANAGED_DASHBOARD_FILENAME)" in sync
    assert "hass.config.path(AGILE_DASHBOARD_FILENAME)" not in sync
    assert "Updated managed KEMS master dashboard with Agile Smart Export views" in sync


def test_kems_setup_syncs_managed_dashboard() -> None:
    """Integration startup must refresh the managed master dashboard in /config."""
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
