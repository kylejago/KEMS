"""Regression coverage for Alpha7.45 Agile battery-plan clarity."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha745_plan_clarity.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "alpha745-agile-plan-clarity.md"


def test_alpha745_release_version_keeps_web20_and_panel7() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.7.0-alpha7.46"
    assert bundle["components"]["property_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["pi_agent"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["public_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel7"


def test_alpha745_module_parses_and_installs_after_alpha744() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))
    loader = LOADER.read_text(encoding="utf-8")

    assert "install_alpha745_plan_clarity_patch" in loader
    assert loader.rindex("install_alpha745_plan_clarity_patch()") > loader.rindex(
        "install_alpha744_dashboard_parity_patch()"
    )


def test_alpha745_exposes_current_soc_and_target_coverage() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "Battery plan to next cheap period" in source
    assert "simulated_soc_percent" in source
    assert "target_soc_percent" in source
    assert "known_price_planned_export_kwh" in source
    assert "unknown_price_capacity_reserved_kwh" in source
    assert "required_from_unknown_slots_kwh" in source
    assert "unaccounted_export_requirement_kwh" in source
    assert "projected_soc_after_known_plan_percent" in source
    assert "projected_soc_with_reserved_capacity_percent" in source
    assert "target_covered" in source


def test_alpha745_dashboard_shows_live_and_simulated_battery_soc() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "sensor.kems_battery_state_of_charge" in source
    assert "sensor.kems_agile_simulated_battery_soc_now" in source
    assert "| Battery SOC |" in source


def test_alpha745_unknown_slot_rows_show_reserved_capacity() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "reserved_unknown_slot_capacity_kwh" in source
    assert "currently_needed_from_this_unknown_capacity_kwh" in source
    assert "kWh capacity reserved" in source
    assert "currently needed" in source
    assert "unknown_prices_are_never_guessed" in source


def test_alpha745_remains_reporting_only() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"reporting_only": True' in source
    assert '"hardware_writes": "blocked"' in source


def test_alpha745_documentation_records_why_partial_plan_looks_small() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "0.7.0-alpha7.45" in source
    assert "published-price allocations" in source
    assert "unpublished-slot capacity" in source
    assert "10%" in source
    assert "Real FoxESS hardware writes remain blocked" in source
