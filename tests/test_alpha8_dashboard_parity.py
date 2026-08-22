"""Parity contracts for canonical Alpha8 Agile dashboard reporting."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
CANONICAL = KEMS / "agile_dashboard_parity.py"


def test_canonical_dashboard_parity_parses() -> None:
    ast.parse(CANONICAL.read_text(encoding="utf-8"), filename=str(CANONICAL))


def test_same_window_today_summary_preserves_alpha744_reporting_contract() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "Today so far — actual vs Full KEMS Agile" in source
    assert "same midnight-to-now demand window" in source
    assert "house_load_kwh" in source
    assert "solar_generation_kwh" in source
    assert "grid_to_battery_kwh" in source
    assert "headline_bill_pence" in source
    assert "energy_net_cost_pence" in source
    assert "economic_outcome_pence" in source
    assert '"same_demand_window_as_actual": True' in source


def test_missing_physical_sources_remain_unavailable() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "Missing physical solar/battery sources remain unavailable" in source
    assert "sensor.kems_agile_live_today_summary" in source
    assert "rather than being replaced with zero" in source


def test_half_hour_slot_decisions_remain_complete_and_do_not_guess_prices() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "Today's Agile half-hour slots and decisions" in source
    assert "settlement_period_minutes" in source
    assert "timedelta(minutes=30)" in source
    assert "Waiting for Octopus price — capacity reserved" in source
    assert "Power Down — house first + maximum safe export" in source
    assert "Happy Hour — maximum safe battery charge" in source
    assert "Happy Hour prep — export" in source
    assert "Cheap period — charge battery / home from grid" in source
    assert "Planned battery export" in source
    assert '"unpublished_prices_are_not_guessed": True' in source


def test_period_aggregation_keeps_flow_evidence() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "def _augment_aggregate(" in source
    assert '"house_load_kwh"' in source
    assert '"solar_generation_kwh"' in source
    assert '"solar_to_home_kwh"' in source
    assert '"grid_to_battery_kwh"' in source
    assert "agile._aggregate = _augment_aggregate" in source


def test_dashboard_parity_remains_reporting_only() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"reporting_only": True' in source
    assert '"hardware_writes": "blocked"' in source
    assert "Real FoxESS hardware writes remain blocked" in source
