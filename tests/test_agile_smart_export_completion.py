"""Regression coverage for completed Agile Smart Export reporting."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime_base.py"
RUNTIME_LOADER = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"
REPORTING = ROOT / "custom_components" / "kems" / "agile_smart_export_reporting.py"
DASHBOARD = ROOT / "dashboards" / "kems_agile_smart_export_builtin.yaml"
PACKAGED = (
    ROOT / "custom_components" / "kems" / "kems_agile_smart_export_dashboard.yaml"
)


def test_agile_runtime_exposes_coverage_gated_365_day_history() -> None:
    """A 12-month headline must never imply missing historical days exist."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert "TWELVE_MONTH_DAYS = 365" in content
    assert 'periods["365_days"] = _aggregate(' in content
    assert 'period["complete_window"] = included >= expected' in content
    assert '"twelve_month_ready": bool(rolling.get("complete_window"))' in content
    assert 'winner = f"Collecting {rolling_days}/{TWELVE_MONTH_DAYS} days"' in content


def test_agile_runtime_publishes_same_dispatch_fixed_12p_benchmark() -> None:
    """Tariff value must be separable from dispatch-strategy value."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert "sensor.kems_agile_vs_fixed_12p_gain_" in content
    assert "sensor.kems_fixed_12p_same_dispatch_income_" in content
    assert '"comparison_boundary": "same Agile Smart Export dispatch"' in content
    assert '"fixed_export_rate_pence": 12.0' in content


def test_agile_runtime_makes_solar_first_routing_visible() -> None:
    """The UI must make home-first PV routing explicit rather than implying cycling."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert "_enrich_slot_routing(" in content
    assert "_annotate_solar_first_display(state)" in content
    assert '"solar_to_home_kwh"' in content
    assert '"sensor.kems_agile_solar_to_home_today"' in content
    assert '"solar to home first"' in content
    assert "only surplus solar is considered" in content


def test_agile_runtime_publishes_panel_compatible_current_flow() -> None:
    """The ESPHome panel must receive the exact existing compact flow protocol."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert '"sensor.kems_agile_smart_export_flow_now"' in content
    assert '"protocol": "KEMS panel flow v1"' in content
    assert "AGILE_FLOW_UNAVAILABLE" in content
    assert "f\"H={power('house_load_kwh'):.3f},\"" in content
    assert "f\"S={power('solar_generation_kwh'):.3f},\"" in content
    assert "f\"GI={power('grid_import_kwh'):.3f},\"" in content
    assert "f\"GE={power('grid_export_kwh'):.3f},\"" in content
    assert "f\"SH={power('solar_to_home_kwh'):.3f},\"" in content
    assert "f\"SB={power('solar_to_battery_kwh'):.3f},\"" in content
    assert "f\"SE={power('solar_export_kwh'):.3f},\"" in content
    assert "f\"GB={power('grid_to_battery_kwh'):.3f},\"" in content
    assert "f\"BH={power('battery_to_home_kwh'):.3f},\"" in content
    assert "f\"BE={power('battery_export_kwh'):.3f},\"" in content
    assert "f\"SOC={float(current_slot['ending_soc_percent']):.1f}\"" in content


def test_agile_solar_to_home_reporting_patch_is_loaded() -> None:
    """Daily totals and Today's detail must retain Solar -> Home on both strategies."""
    loader = RUNTIME_LOADER.read_text(encoding="utf-8")
    reporting = REPORTING.read_text(encoding="utf-8")
    assert "install_reporting_patch()" in loader
    assert "aggregate_with_solar_to_home" in reporting
    assert 'period[strategy_name]["solar_to_home_kwh"]' in reporting
    assert "full.simulated_solar_to_home_kwh" in reporting
    assert "| Solar → home |" in reporting
    assert "_combined_master_dashboard_bytes" in reporting


def test_agile_reporting_exposes_live_and_planned_soc() -> None:
    """Forecast vs Agile must show actual SOC and the current-slot Agile SOC plan."""
    reporting = REPORTING.read_text(encoding="utf-8")
    assert "sensor.kems_agile_planned_battery_soc_now" in reporting
    assert "sensor.kems_battery_state_of_charge" in reporting
    assert "Live battery SOC" in reporting
    assert "Agile planned SOC — end of current slot" in reporting
    assert "ending_soc_percent" in reporting
    assert "| End battery SOC |" in reporting


def test_agile_reporting_labels_12p_as_hypothetical_benchmark() -> None:
    """The UI must never imply that Agile itself has a fixed 12p export rate."""
    reporting = REPORTING.read_text(encoding="utf-8")
    assert "Hypothetical fixed-rate benchmark today" in reporting
    assert "Hypothetical income at 12p — same dispatch" in reporting
    assert "Extra income from Agile pricing vs 12p benchmark" in reporting
    assert "12p is only a hypothetical benchmark" in reporting
    assert "it is not an Agile rate" in reporting


def test_agile_dashboard_surfaces_history_coverage_and_tariff_benchmark() -> None:
    """The managed UI must expose the new 365-day and tariff-only results."""
    content = DASHBOARD.read_text(encoding="utf-8")
    assert "sensor.kems_agile_history_coverage" in content
    assert "sensor.kems_full_kems_forecast_vs_agile_winner_365_days" in content
    assert "sensor.kems_agile_vs_fixed_12p_gain_365_days" in content
    assert "sensor.kems_agile_vs_fixed_12p_gain_today" in content
    assert "365/365 valid daily replays" in content


def test_agile_dashboard_surfaces_solar_to_home_and_battery_preservation() -> None:
    """Solar routing must be visible at headline and half-hour plan level."""
    content = DASHBOARD.read_text(encoding="utf-8")
    assert "sensor.kems_agile_solar_to_home_today" in content
    assert "Solar-first battery preservation" in content
    assert "Solar → home today" in content
    assert "Solar → home | Solar → battery" in content
    assert "Solar-first home rule" in content


def test_packaged_agile_dashboard_matches_repository_source() -> None:
    """HACS must ship the exact Agile dashboard validated in the repository."""
    assert DASHBOARD.read_bytes() == PACKAGED.read_bytes()
