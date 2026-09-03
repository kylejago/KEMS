"""End-to-end contracts for the final Full KEMS Agile dispatch boundary."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MODULE = KEMS / "agile_dispatch_reconciliation.py"
COMPAT = KEMS / "agile_alpha7_compat.py"
CORE = KEMS / "agile_smart_export.py"


def _function_nodes(*names: str) -> ast.Module:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    wanted = set(names)
    body = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    assert {node.name for node in body} == wanted
    return ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))


@dataclass(frozen=True)
class _ReplaySnapshot:
    timestamp: datetime
    off_peak: bool = False
    intelligent_slot: bool = False
    current_import_rate: float = 20.0
    next_import_rate: float = 20.0
    forecast_maximum_overnight_soc_percent: float | None = 80.0


def test_happy_hour_replay_is_free_charge_only_inside_the_event() -> None:
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "replace": replace,
        "agile": SimpleNamespace(LONDON=UTC),
    }
    event = {
        "start": datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
        "end": datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
    }
    namespace["_event_for_replay_day"] = lambda self, day: event
    namespace["_power_down_active"] = lambda snapshot, moment: False
    exec(
        compile(_function_nodes("_happy_hour_replay_records"), str(MODULE), "exec"),
        namespace,
    )

    records = [
        _ReplaySnapshot(datetime(2026, 8, 23, 8, 30, tzinfo=UTC)),
        _ReplaySnapshot(datetime(2026, 8, 23, 9, 0, tzinfo=UTC)),
        _ReplaySnapshot(datetime(2026, 8, 23, 9, 30, tzinfo=UTC)),
        _ReplaySnapshot(datetime(2026, 8, 23, 10, 0, tzinfo=UTC)),
    ]
    projected = namespace["_happy_hour_replay_records"](object(), records)

    assert projected[0] == records[0]
    assert projected[3] == records[3]
    for index in (1, 2):
        assert projected[index] is not records[index]
        assert projected[index].off_peak is True
        assert projected[index].intelligent_slot is False
        assert projected[index].current_import_rate == 0.0
        assert projected[index].next_import_rate == 0.0
        assert projected[index].forecast_maximum_overnight_soc_percent == 100.0

    # Replay projection must never mutate retained KEMS observations.
    assert all(item.off_peak is False for item in records)
    assert all(item.current_import_rate == 20.0 for item in records)


def test_happy_hour_replay_yields_to_power_down_priority() -> None:
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "replace": replace,
        "agile": SimpleNamespace(LONDON=UTC),
    }
    event = {
        "start": datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
        "end": datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
    }
    namespace["_event_for_replay_day"] = lambda self, day: event
    namespace["_power_down_active"] = lambda snapshot, moment: True
    exec(
        compile(_function_nodes("_happy_hour_replay_records"), str(MODULE), "exec"),
        namespace,
    )

    record = _ReplaySnapshot(datetime(2026, 8, 23, 9, 30, tzinfo=UTC))
    projected = namespace["_happy_hour_replay_records"](object(), [record])
    assert projected == [record]


def test_final_charge_route_has_one_site_meter_direction() -> None:
    class SimulationConfig:
        def __init__(self) -> None:
            self.max_charge_kw = 7.0
            self.inverter_limit_kw = 10.0
            self.export_limit_kw = 10.0
            self.site_import_limit_kw = None

    namespace: dict[str, Any] = {
        "Any": Any,
        "math": math,
        "SimulationConfig": SimulationConfig,
        "_current_soc": lambda state: 50.0,
    }
    exec(
        compile(_function_nodes("_number", "_charge_route"), str(MODULE), "exec"),
        namespace,
    )
    owner = SimpleNamespace(_rolling_config=SimulationConfig())
    route = namespace["_charge_route"](
        owner,
        {},
        {"simulated_house_load_kw": 2.0, "solar_power_kw": 1.0},
        charge_target_kw=7.0,
        dispatch_mode="happy_hour_charge",
        action="test",
    )

    assert route["grid_import_kw"] == 8.0
    assert route["grid_export_kw"] == 0.0
    assert route["solar_to_home_kw"] == 1.0
    assert route["grid_to_battery_kw"] == 7.0
    assert route["battery_to_home_kw"] == 0.0
    assert route["battery_export_kw"] == 0.0
    assert route["total_discharge_kw"] == 0.0
    assert route["site_meter_direction_reconciled"] is True


def test_final_charge_route_uses_solar_before_import_and_exports_only_surplus() -> None:
    class SimulationConfig:
        def __init__(self) -> None:
            self.max_charge_kw = 7.0
            self.inverter_limit_kw = 10.0
            self.export_limit_kw = 10.0
            self.site_import_limit_kw = None

    namespace: dict[str, Any] = {
        "Any": Any,
        "math": math,
        "SimulationConfig": SimulationConfig,
        "_current_soc": lambda state: 50.0,
    }
    exec(
        compile(_function_nodes("_number", "_charge_route"), str(MODULE), "exec"),
        namespace,
    )
    owner = SimpleNamespace(_rolling_config=SimulationConfig())
    route = namespace["_charge_route"](
        owner,
        {},
        {"simulated_house_load_kw": 1.0, "solar_power_kw": 10.0},
        charge_target_kw=7.0,
        dispatch_mode="happy_hour_charge",
        action="test",
    )

    assert route["solar_to_home_kw"] == 1.0
    assert route["solar_to_battery_kw"] == 7.0
    assert route["grid_to_battery_kw"] == 0.0
    assert route["grid_import_kw"] == 0.0
    assert route["grid_export_kw"] == 2.0
    assert not (route["grid_import_kw"] > 0 and route["grid_export_kw"] > 0)


def test_reconciliation_is_the_last_canonical_runtime_boundary() -> None:
    source = COMPAT.read_text(encoding="utf-8")
    previous_module = "agile_publication_reporting"
    previous_installer = "install_tomorrow_publication_reporting"
    final_module = "agile_dispatch_reconciliation"
    final_installer = "install_dispatch_reconciliation"

    assert previous_module in source
    assert previous_installer in source
    assert final_module in source
    assert final_installer in source
    assert source.index(final_module) > source.index(previous_module)
    assert source.index(final_installer) > source.index(previous_installer)
    assert "agile_alpha8" not in MODULE.name


def test_user_policy_stays_100_percent_charge_with_one_reserve_hierarchy() -> None:
    source = MODULE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '"charge_target_soc_percent": 100.0' in source
    assert '"planning_target_soc_percent": planning_target' in source
    assert 'rolling_plan.get("hard_safety_floor_soc_percent")' in source
    assert 'rolling_plan.get("hard_safety_recovery_soc_percent")' in source
    assert '"reserve_hierarchy_source": "final rolling_export_plan"' in source
    assert '"battery_reserve_target_soc_percent"' not in source
    assert "forecast_maximum_overnight_soc_percent=100.0" in source
    assert "config.battery_reserve_percent" in core
    assert "recharge_feasibility_floor" not in source


def test_happy_hour_completion_auto_clears_planning_but_keeps_evidence() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "async_set_runtime_options" in source
    assert "CONF_HAPPY_HOUR_ENABLED: False" in source
    assert "weekend_happy_hour_last_completed_start" in source
    assert "weekend_happy_hour_last_completed_end" in source
    assert "weekend_happy_hour_last_completed_duration_hours" in source
    assert '"planning_auto_cleared": True' in source
    assert "_schedule_completed_event_auto_clear" in source
    assert "event_with_completed_fallback" in source


def test_happy_hour_replay_owns_soc_and_old_overlay_is_disabled() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_happy_hour_replay_records" in source
    assert "agile.AgileSmartExportManager._agile_day" in source
    assert "replay_owned_happy_hour_soc" in source
    assert "events._corrected_happy_hour_soc = replay_owned_happy_hour_soc" in source
    assert "_EVENT_DIRECT_GRAPH_IDS" in source
    assert "_kems_suppress_event_graph_overlay" in source


def test_shadow_command_carries_the_same_charge_target() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert 'plan.get("current_battery_charge_target_kw")' in source
    assert '"Force Charge" if charge > _EPSILON' in source
    assert "desired_charge_power_kw=round(charge, 3)" in source
    assert 'parity["charge_target_matches_optimizer"]' in source
    assert 'getattr(control, "desired_charge_power_kw", None)' in source


def test_reconciliation_cannot_enable_real_hardware_writes() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source
