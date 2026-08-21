"""Regression coverage for Alpha7.44 Agile dashboard parity."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha744_dashboard_parity.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "alpha744-agile-dashboard-parity.md"


def test_alpha744_contract_is_coordinated_in_alpha8() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.0"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.0"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.0"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.0"


def test_alpha744_module_parses_and_installs_after_alpha743() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))
    loader = LOADER.read_text(encoding="utf-8")

    assert "install_alpha744_dashboard_parity_patch" in loader
    assert loader.rindex("install_alpha744_dashboard_parity_patch()") > loader.rindex(
        "install_alpha743_event_priority_patch()"
    )


def test_alpha744_today_table_is_same_window_and_uses_headline_bill() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "Today so far — actual vs Full KEMS Agile" in source
    assert "same midnight-to-now demand window" in source
    assert "house_load_kwh" in source
    assert "solar_generation_kwh" in source
    assert "grid_to_battery_kwh" in source
    assert "headline_bill_pence" in source
    assert "energy_net_cost_pence" in source
    assert "economic_outcome_pence" in source


def test_alpha744_keeps_missing_live_physical_sources_unavailable() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "Missing physical solar/battery sources remain unavailable" in source
    assert "sensor.kems_agile_live_today_summary" in source


def test_alpha744_shows_every_half_hour_decision_without_guessing_prices() -> None:
    source = PATCH.read_text(encoding="utf-8")

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


def test_alpha744_remains_reporting_only() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"reporting_only": True' in source
    assert '"hardware_writes": "blocked"' in source


def test_alpha744_documentation_records_dashboard_contract() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "0.7.0-alpha7.44" in source
    assert "local midnight to the latest retained sample" in source
    assert "30-minute settlement tariff" in source
    assert "Waiting for Octopus price — capacity reserved" in source
    assert "Real FoxESS hardware writes remain blocked" in source
