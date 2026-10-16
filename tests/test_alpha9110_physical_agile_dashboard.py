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
