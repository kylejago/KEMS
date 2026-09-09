"""Alpha9.16 Recorder attribute-size regression contracts."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
RECORDER_MAX_ATTRIBUTE_BYTES = 16_384


def _size(value: object) -> int:
    """Return compact JSON byte size, matching Recorder's relevant bound."""
    return len(
        json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).encode()
    )


def _recorded(
    attributes: dict[str, object], unrecorded: frozenset[str]
) -> dict[str, object]:
    """Return the attributes Recorder is allowed to retain."""
    return {key: value for key, value in attributes.items() if key not in unrecorded}


def _hygiene_tree() -> ast.Module:
    """Parse the Recorder hygiene module without importing Home Assistant."""
    return ast.parse(HYGIENE.read_text(encoding="utf-8"), filename=str(HYGIENE))


def _frozenset_constant(name: str) -> frozenset[str]:
    """Read one literal frozenset constant from the Recorder hygiene module."""
    for node in _hygiene_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1
        ):
            return frozenset(ast.literal_eval(value.args[0]))
    raise AssertionError(f"Missing literal frozenset constant {name}")


def _class_assignment(class_name: str, attribute: str) -> ast.expr:
    """Return one class-level assignment expression from the hygiene module."""
    for node in _hygiene_tree().body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and target.id == attribute
                for target in item.targets
            ):
                return item.value
    raise AssertionError(f"Missing {class_name}.{attribute}")


def _large_slots() -> list[dict[str, object]]:
    """Build realistic rich half-hour presentation rows over the 16 KiB limit."""
    return [
        {
            "label": f"{index // 2:02d}:{(index % 2) * 30:02d}",
            "rate_pence": 10.0 + index / 10,
            "flow_grid_action": "EXPORT/CHARGE",
            "flow_battery_action": "EXPORT",
            "flow_solar_action": "HOME/BATTERY/EXPORT",
            "flow_estimated_soc_percent": 90.0 - index / 2,
            "flow_grid_export_kwh": 2.5,
            "flow_solar_to_home_kwh": 0.4,
            "flow_solar_to_battery_kwh": 0.7,
            "flow_solar_export_kwh": 0.8,
            "flow_battery_to_home_kwh": 0.3,
            "flow_battery_export_kwh": 1.7,
            "presentation_source": "canonical flow presentation",
            "routing_explanation": "x" * 160,
        }
        for index in range(48)
    ]


def _large_scenarios() -> list[dict[str, object]]:
    """Build the rich seven-scenario period payload KEMS exposes live."""
    return [
        {
            "key": f"scenario_{index}",
            "label": f"Scenario {index}",
            "description": "what-if replay result " + "x" * 2_500,
            "ready": True,
            "samples": 1440,
            "data_coverage": 1.0,
            "import_cost_pence": 123.45,
            "export_income_pence": 67.89,
            "house_consumption_kwh": 20.0,
            "grid_import_kwh": 10.0,
            "grid_export_kwh": 8.0,
            "solar_generation_kwh": 14.0,
            "battery_charge_kwh": 12.0,
            "battery_to_home_kwh": 7.0,
            "battery_export_kwh": 5.0,
            "ending_soc_percent": 15.0,
        }
        for index in range(7)
    ]


def test_alpha916_warned_entities_are_routed_through_recorder_safe_entities() -> None:
    """All five reported Recorder offenders must have an unrecorded boundary."""
    scenario_keys = _frozenset_constant("SCENARIO_RECORDER_SAFE_KEYS")
    scenario_unrecorded = _frozenset_constant("SCENARIO_UNRECORDED_ATTRIBUTES")
    agile_unrecorded = _frozenset_constant("AGILE_SLOTS_UNRECORDED_ATTRIBUTES")
    energy_unrecorded = _frozenset_constant("ENERGY_COST_UNRECORDED_ATTRIBUTES")

    assert {
        "scenario_comparison_today",
        "scenario_comparison_7_days",
        "scenario_comparison_30_days",
    } <= scenario_keys
    assert {"periods", "timeline", "scenarios"} <= scenario_unrecorded
    assert {
        "today_slots",
        "tomorrow_slots",
        "today_agile",
        "current_day_settlement_reconciliation",
    } <= agile_unrecorded
    assert energy_unrecorded == {"periods"}

    for class_name, constant_name in (
        ("RecorderSafeScenarioSensor", "SCENARIO_UNRECORDED_ATTRIBUTES"),
        ("KEMSAgileSlotsSensor", "AGILE_SLOTS_UNRECORDED_ATTRIBUTES"),
        ("KEMSEnergyCostComparisonSensor", "ENERGY_COST_UNRECORDED_ATTRIBUTES"),
    ):
        value = _class_assignment(class_name, "_unrecorded_attributes")
        assert isinstance(value, ast.Name)
        assert value.id == constant_name

    agile_name = _class_assignment("KEMSAgileSlotsSensor", "_attr_name")
    energy_name = _class_assignment("KEMSEnergyCostComparisonSensor", "_attr_name")
    assert isinstance(agile_name, ast.Constant) and agile_name.value == "Agile slots"
    assert (
        isinstance(energy_name, ast.Constant)
        and energy_name.value == "Energy cost comparison"
    )


def test_alpha916_agile_slots_keep_rich_live_data_without_recording_it() -> None:
    """Slot arrays stay live for HA/Pi-Web while Recorder sees a compact summary."""
    slots = _large_slots()
    attributes: dict[str, object] = {
        "region": "L",
        "product_code": "AGILE-OUTGOING-19-05-13",
        "current_rate_pence": 18.2,
        "current_action": "battery to home",
        "today_count": 48,
        "today_expected": 48,
        "today_complete": True,
        "tomorrow_count": 48,
        "tomorrow_expected": 48,
        "tomorrow_complete": True,
        "today_slots": slots,
        "tomorrow_slots": slots,
        "today_agile": {"summary": "x" * 4_000},
        "current_day_settlement_reconciliation": {"detail": "x" * 4_000},
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    unrecorded = _frozenset_constant("AGILE_SLOTS_UNRECORDED_ATTRIBUTES")
    assert _size(attributes) > RECORDER_MAX_ATTRIBUTE_BYTES
    recorded = _recorded(attributes, unrecorded)
    assert _size(recorded) < RECORDER_MAX_ATTRIBUTE_BYTES
    assert attributes["today_slots"] == slots
    assert attributes["tomorrow_slots"] == slots


def test_alpha916_energy_cost_periods_stay_live_without_recording_them() -> None:
    """Canonical bill periods remain available to the dashboard but not Recorder."""
    period = {
        "label": "Last 30 days",
        "live_data": {"detail": "x" * 5_000},
        "kems": {"detail": "x" * 5_000},
        "saving_pence": 123.4,
    }
    attributes: dict[str, object] = {
        "contract_version": 2,
        "headline": "Total energy cost",
        "basis": "bill_equivalent",
        "selected_kems_strategy": "agile",
        "selected_kems_strategy_label": "Agile Smart Export",
        "periods": {key: period for key in ("today", "7_days", "30_days")},
        "today_live_total_energy_cost_pence": 100.0,
        "today_kems_total_energy_cost_pence": 80.0,
        "today_saving_pence": 20.0,
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    unrecorded = _frozenset_constant("ENERGY_COST_UNRECORDED_ATTRIBUTES")
    assert _size(attributes) > RECORDER_MAX_ATTRIBUTE_BYTES
    recorded = _recorded(attributes, unrecorded)
    assert _size(recorded) < RECORDER_MAX_ATTRIBUTE_BYTES
    assert "periods" in attributes


def test_alpha916_scenario_detail_stays_live_without_recording_it() -> None:
    """Scenario arrays/timeline remain live while compact period metadata records."""
    scenarios = _large_scenarios()
    period_attributes: dict[str, object] = {
        "key": "30_days",
        "label": "Last 30 days",
        "start_date": "2026-08-11",
        "end_date": "2026-09-09",
        "days_included": 30,
        "cheapest_scenario": "kems_full",
        "scenarios": scenarios,
    }
    unrecorded = _frozenset_constant("SCENARIO_UNRECORDED_ATTRIBUTES")
    assert _size(period_attributes) > RECORDER_MAX_ATTRIBUTE_BYTES
    recorded_period = _recorded(period_attributes, unrecorded)
    assert _size(recorded_period) < RECORDER_MAX_ATTRIBUTE_BYTES
    assert period_attributes["scenarios"] == scenarios

    comparison_attributes: dict[str, object] = {
        "generated_at": "2026-09-09T05:23:31+01:00",
        "periods": {"today": period_attributes, "30_days": period_attributes},
        "timeline": [{"timestamp": index, "detail": "x" * 400} for index in range(49)],
    }
    assert _size(comparison_attributes) > RECORDER_MAX_ATTRIBUTE_BYTES
    recorded_comparison = _recorded(comparison_attributes, unrecorded)
    assert _size(recorded_comparison) < RECORDER_MAX_ATTRIBUTE_BYTES


def test_alpha916_setup_retires_legacy_manual_state_publishers() -> None:
    """The affected states must be owned by SensorEntity, not hass.states.async_set."""
    source = (KEMS / "__init__.py").read_text(encoding="utf-8")
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert "install_alpha916_recorder_hygiene()" in source
    assert "async_setup_energy_bill_state(" not in source
    assert "async_setup_agile_slots_state(" not in source
    assert "KEMSAgileSlotsSensor" in hygiene
    assert "KEMSEnergyCostComparisonSensor" in hygiene


def test_alpha916_is_presentation_only_and_cannot_write_hardware() -> None:
    """Recorder hygiene must not alter optimisation, commissioning, or writes."""
    source = HYGIENE.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "forecast_path_scheduler" not in source
    assert "system_profile" not in source
    assert "commands_permitted = True" not in source
    assert "safe_to_write_hardware = True" not in source
