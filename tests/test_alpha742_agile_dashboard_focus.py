"""Regression coverage for Alpha7.42 focused Full KEMS Agile dashboard."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
FOCUS = KEMS / "agile_alpha742_dashboard_focus.py"
LIVE = KEMS / "agile_alpha742_live_graph_telemetry.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "alpha742-focused-agile-dashboard.md"


def test_alpha742_contract_is_coordinated_in_alpha8() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    web_versions = {
        str(bundle["components"][component]["version"])
        for component in ("property_web", "pi_agent", "public_web")
    }
    assert len(web_versions) == 1
    web_version = web_versions.pop()
    assert web_version.startswith("0.8.0-alpha8-web.")
    assert int(web_version.rsplit(".", 1)[1]) >= 2
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"


def test_alpha742_modules_parse() -> None:
    ast.parse(FOCUS.read_text(encoding="utf-8"))
    ast.parse(LIVE.read_text(encoding="utf-8"))


def test_alpha742_installs_after_alpha741() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha742_dashboard_focus_patch" in loader
    assert "install_alpha742_live_graph_telemetry_patch" in loader
    assert loader.rindex("install_alpha742_dashboard_focus_patch()") > loader.rindex(
        "install_alpha741_partial_publication_dashboard_patch()"
    )
    assert loader.rindex(
        "install_alpha742_live_graph_telemetry_patch()"
    ) > loader.rindex("install_alpha742_dashboard_focus_patch()")


def test_alpha742_dashboard_is_live_vs_simulation_first() -> None:
    source = FOCUS.read_text(encoding="utf-8")
    assert "Full KEMS Agile — live vs simulation" in source
    assert "Live / actual now" in source
    assert "Full KEMS Agile simulation now" in source
    assert "Actual power — last 24 hours" in source
    assert "Full KEMS Agile simulated power — last 24 hours" in source
    assert "Today totals — actual vs Full KEMS Agile" in source
    assert "Period cost summary" in source


def test_alpha742_graphs_include_house_solar_battery_and_grid() -> None:
    focus = FOCUS.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    for entity_id in (
        "sensor.kems_agile_simulated_house_load_power",
        "sensor.kems_agile_simulated_solar_power",
        "sensor.kems_agile_simulated_battery_net_power",
        "sensor.kems_agile_simulated_grid_import_power",
        "sensor.kems_agile_simulated_grid_export_power",
    ):
        assert entity_id in focus
    for entity_id in (
        "sensor.kems_agile_actual_house_load_power",
        "sensor.kems_agile_actual_solar_power",
        "sensor.kems_agile_actual_battery_net_power",
        "sensor.kems_agile_actual_grid_import_power",
        "sensor.kems_agile_actual_grid_export_power",
    ):
        assert entity_id in live


def test_alpha742_missing_live_sources_are_not_zero_filled() -> None:
    focus = FOCUS.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    assert '"unavailable"' in focus
    assert '"unavailable"' in live
    assert '"missing_sources_remain_unavailable": True' in focus
    assert '"missing_physical_data_is_not_zero": True' in live
    assert "KEMS does not replace missing live solar/battery data with zero" in focus


def test_alpha742_live_daily_summary_tracks_energy_flows() -> None:
    source = FOCUS.read_text(encoding="utf-8")
    for key in (
        "house_energy_kwh",
        "solar_generation_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
        "battery_charge_kwh",
        "battery_discharge_kwh",
    ):
        assert key in source
    assert "battery_power_positive_is_discharge" in source


def test_alpha742_remains_reporting_only() -> None:
    focus = FOCUS.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    for source in (focus, live):
        assert ".services.async_call(" not in source
        assert "providers.foxess" not in source
        assert '"hardware_writes": "blocked"' in source
        assert '"reporting_only": True' in source


def test_alpha742_documentation_records_dashboard_and_safety_contract() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.42" in source
    assert "Actual power — last 24 hours" in source
    assert "Full KEMS Agile simulated power — last 24 hours" in source
    assert "does not turn missing physical data into zero" in source
    assert "10% battery reserve" in source
    assert "Real FoxESS hardware writes remain blocked" in source
