"""Alpha9.110 Live Data Agile SOC must never borrow the depleted digital twin."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components/kems/agile_slots_state.py"
DASHBOARD = ROOT / "custom_components/kems/kems_master_dashboard.yaml"


def _outlook():
    """Load only pure projection helpers; do not require Home Assistant in CI."""
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    funcs = {
        "_utc_time",
        "_finite_nonnegative",
        "_physical_live_slot_outlook",
    }
    helpers = ast.Module(
        body=[
            node
            for node in parsed.body
            if isinstance(node, ast.FunctionDef) and node.name in funcs
        ],
        type_ignores=[],
    )
    assert len(helpers.body) == 3
    namespace: dict[str, Any] = {
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "Any": Any,
    }
    exec(compile(helpers, str(SOURCE), "exec"), namespace)
    return namespace["_physical_live_slot_outlook"]


def _data(*, verified: bool = True, stale: bool = False, solar: float = 0.0):
    now = datetime.now(UTC)
    first = now + timedelta(minutes=2)
    second = first + timedelta(minutes=30)
    third = second + timedelta(minutes=30)
    items = [
        {
            "valid_from": first.isoformat(),
            "valid_to": second.isoformat(),
            "planned_total_discharge_kwh": 5.0,
            "planned_battery_export_kwh": 4.0,
            "planned_house_battery_kwh": 1.0,
        },
        {
            "valid_from": second.isoformat(),
            "valid_to": third.isoformat(),
            "planned_total_discharge_kwh": 10.0,
            "planned_battery_export_kwh": 0.0,
            "planned_house_battery_kwh": 10.0,
        },
    ]
    generated = now - timedelta(minutes=6) if stale else now
    return {
        "rolling_export_plan": {
            "available": True,
            "generated_at": generated.isoformat(),
            "planning_soc_percent": 60.0,
            "planning_soc_source": (
                "verified FoxESS physical lower bound"
                if verified
                else "settled current-day digital-twin SOC"
            ),
            "physical_planning_evidence": {"available": verified},
            "forecast_path_scheduler": {
                "available": True,
                "active": True,
                "future_solar_borrowing": False,
                "forecast_solar_stored_kwh": solar,
                "ending_soc_percent": 30.0,
                "allocations": items,
            },
        }
    }, items


def _coordinator():
    return SimpleNamespace(
        settings=SimpleNamespace(
            simulation=SimpleNamespace(
                battery_capacity_kwh=50.0,
                discharge_efficiency=1.0,
            )
        )
    )


def test_live_slot_soc_uses_physical_initial_state_and_real_ledger() -> None:
    state, items = _data()
    physical = _outlook()(_coordinator(), state)
    assert len(physical) == 2
    first = physical[items[0]["valid_from"]]
    second = physical[items[1]["valid_from"]]
    assert first["estimated_soc_percent"] == 50.0
    assert second["estimated_soc_percent"] == 30.0
    assert first["action"] == "Planned battery export; house first"
    assert second["action"].startswith("Battery powers home")
    assert first["reporting_only"] is True


def test_no_physical_evidence_never_displays_digital_twin_as_live() -> None:
    state, _ = _data(verified=False)
    assert _outlook()(_coordinator(), state) == {}


def test_old_live_plan_never_passes_as_fresh() -> None:
    state, _ = _data(stale=True)
    assert _outlook()(_coordinator(), state) == {}


def test_future_solar_charge_without_chronological_energy_proof_fails_closed() -> None:
    state, _ = _data(solar=1.0)
    assert _outlook()(_coordinator(), state) == {}


def test_live_card_uses_physical_action_and_soc_not_simulated_fields() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    card = source.split("title: Today's Agile plan — now and next", 1)[1].split(
        "      - type: grid", 1
    )[0]
    assert "physical_live_slot_outlook" in card
    assert "physical.get('estimated_soc_percent')" in card
    assert "physical.get('action')" in card
    assert "flow_estimated_soc_percent" not in card
    assert "rolling_action" not in card
    assert "unavailable" in card.lower()


def _inactive_forecast_with_ledger(*, verified: bool = True):
    state, items = _data(verified=verified)
    plan = state["rolling_export_plan"]
    plan["forecast_path_scheduler"] = {
        "available": False,
        "active": False,
        "reason": "waiting for high-confidence hourly solar forecast",
    }
    plan["total_discharge_ledger_active"] = True
    plan["effective_precheap_target_soc_percent"] = 30.0
    plan["total_discharge_ledger"] = {
        "allocations": items,
        "required_total_discharge_kwh": 15.0,
        "allocated_total_discharge_kwh": 15.0,
        "unallocated_total_discharge_kwh": 0.0,
    }
    return state, items


def test_alpha9127_low_confidence_solar_uses_verified_discharge_only_ledger() -> None:
    state, items = _inactive_forecast_with_ledger()
    outlook = _outlook()(_coordinator(), state)
    assert list(outlook) == [item["valid_from"] for item in items]
    assert outlook[items[0]["valid_from"]]["estimated_soc_percent"] == 50.0
    assert outlook[items[1]["valid_from"]]["estimated_soc_percent"] == 30.0
    assert (
        "no speculative solar charging credited"
        in outlook[items[0]["valid_from"]]["basis"]
    )
    assert all(item["reporting_only"] for item in outlook.values())


def test_alpha9127_no_live_physical_proof_never_uses_ledger_or_digital_twin() -> None:
    state, _ = _inactive_forecast_with_ledger(verified=False)
    assert _outlook()(_coordinator(), state) == {}


def test_alpha9127_missing_validated_ledger_remains_unavailable() -> None:
    state, _ = _inactive_forecast_with_ledger()
    del state["rolling_export_plan"]["total_discharge_ledger_active"]
    assert _outlook()(_coordinator(), state) == {}


def test_alpha9127_unknown_future_discharge_cannot_be_hidden_by_ledger() -> None:
    state, _ = _inactive_forecast_with_ledger()
    state["rolling_export_plan"]["total_discharge_ledger"][
        "unallocated_total_discharge_kwh"
    ] = 0.2
    assert _outlook()(_coordinator(), state) == {}


def test_alpha9127_ledger_must_agree_with_physical_discharge_target() -> None:
    state, _ = _inactive_forecast_with_ledger()
    state["rolling_export_plan"]["effective_precheap_target_soc_percent"] = 40.0
    assert _outlook()(_coordinator(), state) == {}


def test_alpha9127_active_unsafe_solar_scheduler_cannot_fallback_to_ledger() -> None:
    state, _ = _inactive_forecast_with_ledger()
    state["rolling_export_plan"]["forecast_path_scheduler"] = {
        "available": True,
        "active": True,
        "future_solar_borrowing": True,
    }
    assert _outlook()(_coordinator(), state) == {}


def test_alpha9127_live_rate_matches_visible_current_half_hour_slot() -> None:
    for rel in (
        "custom_components/kems/kems_master_dashboard.yaml",
        "dashboards/kems_master_dashboard.yaml",
    ):
        source = (ROOT / rel).read_text(encoding="utf-8")
        card = source.split("title: Today's Agile plan — now and next", 1)[1].split(
            "      - type: grid", 1
        )[0]
        assert "slots[0].get('rate_pence')" in card
        assert "idx < (today | count)" in card
        assert "conservative discharge-only physical ledger" in card
        assert "current_rate_pence" not in card
