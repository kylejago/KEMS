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
PIPELINE = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"

EXPECTED_CUSTOMER_PATHS = [
    "home",
    "live-data",
    "kems",
    "compare",
    "agile-slots",
    "history",
    "system",
]


def test_packaged_master_dashboard_matches_repository_source() -> None:
    """HACS must receive the exact dashboard source documented by the repo."""
    assert PACKAGED.exists()
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()


def test_managed_master_dashboard_is_fresh_builtin_yaml() -> None:
    """The customer dashboard should parse with the seven clean Alpha8.19 views."""
    content = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert content["title"] == "KEMS"
    assert [view["path"] for view in content["views"]] == EXPECTED_CUSTOMER_PATHS


def test_managed_dashboard_has_only_live_data_and_kems_products() -> None:
    """Retired strategy engines must not return as customer product views."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert "# Live Data" in content
    assert "# KEMS" in content
    assert "# Live Data vs KEMS" in content
    assert "Battery & Solar" not in content
    assert "Full KEMS Agile" not in content
    assert "Compare every KEMS type" not in content


def test_managed_dashboard_keeps_agile_slots_as_tariff_information() -> None:
    """Half-hour Agile data should remain visible without becoming a product."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert "path: agile-slots" in content
    assert "sensor.kems_agile_slots" in content
    assert "today_slots" in content
    assert "tomorrow_slots" in content
    assert "not another KEMS product" in content


def test_packaged_agile_dashboard_matches_repository_source() -> None:
    """The historical Agile evidence dashboard remains available standalone."""
    assert AGILE_PACKAGED.exists()
    assert AGILE_PACKAGED.read_bytes() == AGILE_SOURCE.read_bytes()


def test_standalone_agile_evidence_dashboard_retains_engineering_views() -> None:
    """Internal Agile evidence is retained even though it is not customer navigation."""
    content = yaml.safe_load(AGILE_PACKAGED.read_text(encoding="utf-8"))
    paths = {view["path"] for view in content["views"]}
    assert {
        "forecast-vs-agile",
        "agile-price-plan",
        "agile-history",
        "agile-assumptions",
    } <= paths


def test_runtime_pipeline_bypasses_historical_master_agile_composition() -> None:
    """The managed customer YAML must be shipped directly without old view appends."""
    pipeline = PIPELINE.read_text(encoding="utf-8")
    assert "PACKAGED_DASHBOARD_PATH.read_bytes()" in pipeline
    assert "dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes" in pipeline
    assert "convergent._managed_dashboard_bytes = _fresh_dashboard_bytes" in pipeline
    assert "PACKAGED_AGILE_DASHBOARD_PATH" not in pipeline
    assert "dashboard_consolidation" not in pipeline


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
