"""Alpha8.73 regressions for deadline-latch lifecycle identity."""

from __future__ import annotations

import ast
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
LATCH = KEMS / "agile_deadline_latch.py"


def _load_latch_functions() -> dict[str, Any]:
    tree = ast.parse(LATCH.read_text(encoding="utf-8"), filename=str(LATCH))
    wanted = {
        "_number",
        "_datetime",
        "_guard",
        "_soc_and_target",
        "_deadline_from",
        "_release_reason",
        "_suppressed_active_guard",
        "_new_latch",
        "_safe_deadline_power",
        "_apply_latch",
        "_dispatch_with_deadline_latch",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)

    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
        "SimulationConfig": Any,
        "_EPSILON": 1e-6,
        "_SOC_TOLERANCE_PERCENT": 0.05,
        "_LATCH_ATTR": "_kems_deadline_discharge_latch",
        "_DEADLINE_MODES": frozenset({"deadline_following", "maximum_discharge"}),
        "_PRICE_MODES": frozenset({"price_optimised", "deadline_following"}),
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(LATCH),
            "exec",
        ),
        namespace,
    )
    return namespace


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
    )


def _economic_targets(
    *,
    deadline: str = "2026-09-03T22:30:00+00:00",
    soc: float = 27.6,
) -> dict[str, Any]:
    return {
        "mode": "price_optimised",
        "action": "hold battery — later higher-value slots safely cover target",
        "house_battery_kw": 0.7,
        "battery_export_target_kw": 0.0,
        "battery_discharge_target_kw": 0.7,
        "deadline_guard_suppressed_by_plan_coverage": False,
        "deadline_guard": {
            "raw_mode": "price_optimised",
            "mode": "price_optimised",
            "deadline_guard_active": False,
            "deadline": deadline,
            "target_soc_percent": 10.0,
            "simulated_soc_percent": soc,
            "required_discharge_kwh": 5.218,
            "solar_aware_deadline_margin_kwh": 59.194,
            "current_battery_headroom_kw": 7.0,
        },
        "solar_aware_inverter_headroom": {
            "battery_inverter_headroom_kw": 7.0,
            "deadline_guard_applied": False,
        },
    }


def _live_plan() -> dict[str, Any]:
    return {
        "exportable_battery_energy_kwh": 5.218,
        "planned_battery_export_kwh": 5.218,
        "selected_slots": [
            {
                "valid_from": "2026-09-03T17:00:00+00:00",
                "valid_to": "2026-09-03T17:30:00+00:00",
                "rate_pence": 24.73,
                "planned_battery_export_kwh": 2.721,
            },
            {
                "valid_from": "2026-09-03T17:30:00+00:00",
                "valid_to": "2026-09-03T18:00:00+00:00",
                "rate_pence": 24.29,
                "planned_battery_export_kwh": 2.497,
            },
        ],
    }


def test_sep2_identityless_latch_cannot_force_sep3_686p_export() -> None:
    """Reproduce the live cross-day symptom and keep the fresh plan economic."""
    ns = _load_latch_functions()
    manager = SimpleNamespace(
        _kems_deadline_discharge_latch={
            "active": True,
            "activated_at": "2026-09-02T18:00:00+00:00",
            "deadline": None,
            "target_soc_percent": 10.0,
            "reason": "guarded latest-safe-start reached",
        }
    )
    state = {
        "home_away_mode": "home",
        "today_slots": [
            {
                "valid_from": "2026-09-03T10:00:00+00:00",
                "valid_to": "2026-09-03T10:30:00+00:00",
                "rate_pence": 6.86,
            }
        ],
    }
    plan = _live_plan()

    def original(self, state, plan, *, now, config, tariff):
        return _economic_targets()

    def forbidden_rebalance(*args, **kwargs):
        raise AssertionError(
            "stale prior-day latch must not rebalance the current slot"
        )

    ns["_original_deadline_latch_dispatch"] = original
    ns["reconciliation"] = SimpleNamespace(
        _rebalance_deadline_forced_current_slot=forbidden_rebalance
    )

    targets = ns["_dispatch_with_deadline_latch"](
        manager,
        state,
        plan,
        now=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
        config=_config(),
        tariff=object(),
    )

    assert targets["mode"] == "price_optimised"
    assert targets["battery_export_target_kw"] == 0.0
    assert targets["deadline_latch_active"] is False
    assert targets["deadline_latch_released"] == "deadline_identity_missing"
    assert manager._kems_deadline_discharge_latch is None
    assert (
        sum(item["planned_battery_export_kwh"] for item in plan["selected_slots"])
        == 5.218
    )
    assert [item["rate_pence"] for item in plan["selected_slots"]] == [24.73, 24.29]
    assert state["home_away_mode"] == "home"


def test_same_deadline_latch_survives_normal_coordinator_refreshes() -> None:
    ns = _load_latch_functions()
    manager = SimpleNamespace(
        _kems_deadline_discharge_latch={
            "active": True,
            "activated_at": "2026-09-03T18:00:00+00:00",
            "deadline": "2026-09-03T22:30:00+00:00",
            "target_soc_percent": 10.0,
            "reason": "guarded latest-safe-start reached",
        }
    )
    state: dict[str, Any] = {"today_slots": []}
    plan: dict[str, Any] = {"selected_slots": []}

    def original(self, state, plan, *, now, config, tariff):
        return _economic_targets(soc=24.0)

    ns["_original_deadline_latch_dispatch"] = original
    ns["reconciliation"] = SimpleNamespace(
        _rebalance_deadline_forced_current_slot=lambda *args, **kwargs: {
            "applied": False,
            "reason": "fixture",
        }
    )

    for minute in (5, 10, 20):
        targets = ns["_dispatch_with_deadline_latch"](
            manager,
            state,
            plan,
            now=datetime(2026, 9, 3, 18, minute, tzinfo=UTC),
            config=_config(),
            tariff=object(),
        )
        assert targets["mode"] == "deadline_following"
        assert targets["deadline_latch_active"] is True
        assert targets["deadline_latch_activated_at"] == "2026-09-03T18:00:00+00:00"
        assert targets["deadline_latch_deadline"] == "2026-09-03T22:30:00+00:00"

    assert manager._kems_deadline_discharge_latch["active"] is True


def test_deadline_identity_advance_releases_once_without_relatching() -> None:
    ns = _load_latch_functions()
    manager = SimpleNamespace(
        _kems_deadline_discharge_latch={
            "active": True,
            "activated_at": "2026-09-03T18:00:00+00:00",
            "deadline": "2026-09-03T22:30:00+00:00",
            "target_soc_percent": 10.0,
            "reason": "guarded latest-safe-start reached",
        }
    )
    state: dict[str, Any] = {"today_slots": []}
    plan: dict[str, Any] = {"selected_slots": []}

    def original(self, state, plan, *, now, config, tariff):
        return _economic_targets(deadline="2026-09-04T22:30:00+00:00", soc=27.6)

    ns["_original_deadline_latch_dispatch"] = original
    ns["reconciliation"] = SimpleNamespace(
        _rebalance_deadline_forced_current_slot=lambda *args, **kwargs: {
            "applied": False
        }
    )

    first = ns["_dispatch_with_deadline_latch"](
        manager,
        state,
        plan,
        now=datetime(2026, 9, 3, 20, 0, tzinfo=UTC),
        config=_config(),
        tariff=object(),
    )
    assert first["deadline_latch_released"] == "deadline_identity_advanced"
    assert first["mode"] == "price_optimised"
    assert manager._kems_deadline_discharge_latch is None

    second = ns["_dispatch_with_deadline_latch"](
        manager,
        state,
        plan,
        now=datetime(2026, 9, 3, 20, 5, tzinfo=UTC),
        config=_config(),
        tariff=object(),
    )
    assert second["mode"] == "price_optimised"
    assert "deadline_latch_released" not in second
    assert "_kems_deadline_discharge_latch" not in manager.__dict__ or (
        manager._kems_deadline_discharge_latch is None
    )


def test_identityless_deadline_mode_is_not_durably_armed() -> None:
    ns = _load_latch_functions()
    manager = SimpleNamespace()
    state: dict[str, Any] = {"today_slots": []}
    plan: dict[str, Any] = {"selected_slots": []}

    def original(self, state, plan, *, now, config, tariff):
        targets = _economic_targets()
        targets["mode"] = "deadline_following"
        targets["deadline_guard"]["raw_mode"] = "deadline_following"
        targets["deadline_guard"]["mode"] = "deadline_following"
        targets["deadline_guard"]["deadline"] = None
        return targets

    ns["_original_deadline_latch_dispatch"] = original
    ns["reconciliation"] = SimpleNamespace(
        _rebalance_deadline_forced_current_slot=lambda *args, **kwargs: {
            "applied": False
        }
    )

    targets = ns["_dispatch_with_deadline_latch"](
        manager,
        state,
        plan,
        now=datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
        config=_config(),
        tariff=object(),
    )
    assert targets["mode"] == "deadline_following"
    assert targets["deadline_latch_active"] is False
    assert targets["deadline_latch_not_armed"] == "deadline_identity_missing"
    assert "_kems_deadline_discharge_latch" not in manager.__dict__


def test_target_and_original_deadline_release_semantics_remain_unchanged() -> None:
    ns = _load_latch_functions()
    latch = {
        "active": True,
        "activated_at": "2026-09-03T18:00:00+00:00",
        "deadline": "2026-09-03T22:30:00+00:00",
        "target_soc_percent": 10.0,
    }
    target_guard = _economic_targets(soc=10.0)["deadline_guard"]
    assert (
        ns["_release_reason"](
            latch,
            target_guard,
            now=datetime(2026, 9, 3, 20, 0, tzinfo=UTC),
        )
        == "target_reached"
    )

    next_guard = _economic_targets(deadline="2026-09-04T22:30:00+00:00", soc=13.4)[
        "deadline_guard"
    ]
    assert (
        ns["_release_reason"](
            latch,
            next_guard,
            now=datetime(2026, 9, 3, 22, 30, tzinfo=UTC),
        )
        == "cheap_window_started"
    )


def test_alpha873_contract_survives_successor_releases() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = LATCH.read_text(encoding="utf-8")

    version = manifest["version"]
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    release_number = int(version.rsplit(".", 1)[1])
    assert release_number >= 73
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    if release_number == 73:
        assert "deadline latch" in bundle["maintenance"]["reason"].lower()
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "commands_permitted = True" not in source
    assert "real hardware writes stay blocked" in source
