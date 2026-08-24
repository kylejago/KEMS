"""Alpha8.10 regressions from 24 August live shadow evidence."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
RECONCILIATION = KEMS / "agile_runtime_reconciliation.py"
COMPAT = KEMS / "agile_alpha7_compat.py"


def _load_functions(names: set[str], constants: set[str] | None = None):
    constants = constants or set()
    tree = ast.parse(RECONCILIATION.read_text(encoding="utf-8"))
    body: list[ast.stmt] = []
    for node in tree.body:
        if (
            (isinstance(node, ast.ImportFrom) and node.module == "__future__")
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id in constants
                    for target in node.targets
                )
            )
            or (isinstance(node, ast.FunctionDef) and node.name in names)
        ):
            body.append(node)
    namespace = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "_EPSILON": 1e-6,
        "_SETTLEMENT_PERIOD": timedelta(minutes=30),
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            "reconciliation",
            "exec",
        ),
        namespace,
    )
    return namespace


def _dt(value):
    if value is None:
        return None
    parsed = (
        value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    )
    return parsed.astimezone(UTC)


def test_selected_slots_gain_explicit_half_hour_bounds() -> None:
    ns = _load_functions({"_normalise_selected_slots"})
    ns["events"] = SimpleNamespace(_dt=_dt)
    start = datetime(2026, 8, 24, 15, 30, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    plan = {
        "selected_slots": [
            {
                "valid_from": start.isoformat(),
                "label": "16:30",
                "rate_pence": 20.10,
                "planned_battery_export_kwh": 2.839,
            }
        ],
        "next_export_slot": {"valid_from": start.isoformat(), "label": "16:30"},
    }
    state = {
        "today_slots": [{"valid_from": start.isoformat(), "valid_to": end.isoformat()}]
    }

    selected = ns["_normalise_selected_slots"](plan, state)

    assert selected[0]["valid_to"] == end.isoformat()
    assert plan["next_export_slot"]["valid_to"] == end.isoformat()


def test_active_power_down_uses_live_house_load_and_one_grid_direction() -> None:
    ns = _load_functions({"_current_live_house_kw", "_active_power_down_targets"})
    snapshot = SimpleNamespace(house_load_kw=5.613, grid_import_kw=5.613)
    ns["events"] = SimpleNamespace(
        _latest_snapshot=lambda self: snapshot,
        _number=lambda value: None if value is None else float(value),
        _current_solar_kw=lambda self, config: 1.043,
    )
    ns["rolling"] = SimpleNamespace(_current_agile_soc=lambda state: 78.5)
    config = SimpleNamespace(
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        battery_reserve_percent=10.0,
    )

    result = ns["_active_power_down_targets"](
        object(), {}, {"available": True, "active": True}, config
    )

    assert result["house_battery_kw"] == 4.57
    assert result["battery_export_target_kw"] == 1.387
    assert result["battery_discharge_target_kw"] == 5.957
    assert result["projected_grid_import_kw"] == 0.0
    assert result["grid_export_target_kw"] == 1.387
    assert not (
        result["projected_grid_import_kw"] > 0 and result["grid_export_target_kw"] > 0
    )
    assert result["active_house_load_basis"] == "current_snapshot"


def test_unknown_future_price_does_not_block_known_current_slot() -> None:
    ns = _load_functions({"_nonblocking_price_horizon"})
    called = {"hold": False}

    def original_hold(state, plan, horizon, *, now):
        called["hold"] = True
        plan["current_battery_export_target_kw"] = 0.0

    ns["_ORIGINAL_HORIZON_HOLD"] = original_hold
    ns["horizon_runtime"] = SimpleNamespace(
        _DEADLINE_OVERRIDE_MODES=frozenset({"deadline_following", "maximum_discharge"})
    )
    plan = {
        "dispatch_mode": "price_optimised",
        "current_battery_export_target_kw": 4.773,
        "selected_slots": [{"label": "16:30"}],
    }
    horizon = {
        "complete": False,
        "current_slot_known": True,
        "missing_labels": ["23:00"],
        "battery_export_held": False,
    }

    ns["_nonblocking_price_horizon"](
        {}, plan, horizon, now=datetime(2026, 8, 24, 15, 35, tzinfo=UTC)
    )

    assert called["hold"] is False
    assert plan["current_battery_export_target_kw"] == 4.773
    assert plan["selected_slots"] == [{"label": "16:30"}]
    assert horizon["status"] == "incomplete_nonblocking"
    assert horizon["unknown_price_capacity_reserved_kwh"] == 0.0
    assert horizon["replan_when_price_publishes"] is True


def test_unknown_current_price_still_holds_for_safety() -> None:
    ns = _load_functions({"_nonblocking_price_horizon"})
    called = {"hold": False}

    def original_hold(state, plan, horizon, *, now):
        called["hold"] = True

    ns["_ORIGINAL_HORIZON_HOLD"] = original_hold
    ns["horizon_runtime"] = SimpleNamespace(_DEADLINE_OVERRIDE_MODES=frozenset())
    horizon = {"complete": False, "current_slot_known": False}
    ns["_nonblocking_price_horizon"](
        {}, {}, horizon, now=datetime(2026, 8, 24, 15, 35, tzinfo=UTC)
    )
    assert called["hold"] is True


def test_maximum_discharge_cannot_zero_a_selected_current_export() -> None:
    ns = _load_functions({"_restore_required_current_export"})
    ns["events"] = SimpleNamespace(
        _number=lambda value: None if value is None else float(value),
        _selected_current_export_kw=lambda selected, now: 4.773,
    )
    plan = {
        "dispatch_mode": "maximum_discharge",
        "current_house_battery_kw": 1.2,
        "current_battery_export_target_kw": 0.0,
    }

    ns["_restore_required_current_export"](
        plan, [{"planned_battery_export_kwh": 2.839}], datetime.now(UTC)
    )

    assert plan["current_battery_export_target_kw"] == 4.773
    assert plan["current_battery_discharge_target_kw"] == 5.973
    assert plan["maximum_discharge_zero_target_reconciled"] is True


def test_daytime_completed_offpeak_end_does_not_fail_tariff_readiness() -> None:
    ns = _load_functions({"_repair_commissioning_tariff_check"})
    ns["commissioning"] = SimpleNamespace(PASS="PASS", WAIT="WAIT", FAIL="FAIL")
    snapshot = SimpleNamespace(
        current_import_rate=28.3036,
        cheap_period_confirmed=False,
        tariff_stale_fields=("offpeak_end",),
    )
    coordinator = SimpleNamespace(data=SimpleNamespace(snapshot=snapshot))
    payload = {
        "state": "Blocked",
        "ready_for_shadow": False,
        "foxess_registered_entity_count": 0,
        "checks": [
            {
                "key": "tariff_data",
                "label": "Tariff data",
                "status": "FAIL",
                "detail": "stale",
                "required": True,
            }
        ],
        "fail_count": 1,
        "wait_count": 0,
        "pass_count": 0,
    }

    ns["_repair_commissioning_tariff_check"](payload, coordinator)

    assert payload["checks"][0]["status"] == "PASS"
    assert "operational stale fields=[]" in payload["checks"][0]["detail"]
    assert payload["state"] == "Awaiting FoxESS"
    assert payload["fail_count"] == 0


def test_reconciliation_is_final_canonical_shadow_only_boundary() -> None:
    compat = COMPAT.read_text(encoding="utf-8")
    source = RECONCILIATION.read_text(encoding="utf-8")
    spec = '("agile_runtime_reconciliation", "install_runtime_reconciliation")'

    assert spec in compat
    assert compat.index(spec) > compat.index(
        '("agile_dispatch_reconciliation", "install_dispatch_reconciliation")'
    )
    assert "agile_alpha810" not in compat
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert 'hardware_writes": "blocked' in source
