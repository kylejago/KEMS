"""Parity contracts for canonical Agile event priority ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
FACADE = KEMS / "agile_event_priority.py"
RUNTIME = KEMS / "agile_event_priority_runtime.py"
HISTORICAL = KEMS / "agile_alpha743_event_priority.py"
COMPAT = KEMS / "agile_alpha7_compat.py"


def test_event_priority_runtime_is_byte_identical_to_proven_alpha743() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_event_priority_facade_is_canonical_and_does_not_import_historical_module() -> (
    None
):
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(FACADE))

    assert "def install_event_priority()" in source
    assert "agile_event_priority_runtime" in source
    assert "agile_alpha743_event_priority" not in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_event_priority_registry_preserves_exact_installation_position() -> None:
    source = COMPAT.read_text(encoding="utf-8")

    live_graph = '"agile_alpha742_live_graph_telemetry"'
    event_priority = '("agile_event_priority", "install_event_priority")'
    dashboard_parity = '("agile_dashboard_parity", "install_dashboard_parity")'

    assert source.index(event_priority) > source.index(live_graph)
    assert source.index(event_priority) < source.index(dashboard_parity)
    assert '"agile_alpha743_event_priority"' not in source


def test_event_priority_keeps_power_down_absolute_over_agile_price() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert '"priority": "absolute_over_agile_price"' in source
    assert '"agile_price_can_override": False' in source
    assert '"solar_forecast_required_for_reserve": False' in source
    assert '"maximise_safe_export": True' in source
    assert '"ev_charging_allowed_during_event": False' in source
    assert '"mode": "power_down_session"' in source
    assert "_apply_power_down_to_plan" in source


def test_event_priority_keeps_happy_hour_known_price_and_replan_contract() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert "_candidate_prep_slots" in source
    assert '"happy_hour_headroom_preparation": True' in source
    assert "never guess a pre/post Happy Hour Agile price" in source
    assert "best_known_post_happy_hour_export_slot" in source
    assert "happy_hour_adjusted_soc_percent" in source
    assert '"mode": "happy_hour_charge"' in source
    assert '"battery_export_target_kw": 0.0' in source
    assert '"battery_discharge_target_kw": 0.0' in source


def test_event_priority_keeps_dispatch_plan_hooks_but_no_hardware_write_path() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert "alpha717._dispatch_targets" in source
    assert "rolling._rolling_plan" in source
    assert "safety > Power Down > Happy Hour > Agile price" in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
