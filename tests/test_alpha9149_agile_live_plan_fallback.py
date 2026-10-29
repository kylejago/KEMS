"""Alpha9.149 operator Agile plan must survive priority-gated physical SOC replay."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
SLOTS = KEMS / "agile_slots_state.py"
DASH = KEMS / "kems_master_dashboard.yaml"


def _helpers() -> dict[str, Any]:
    source = ast.parse(SLOTS.read_text())
    names = {
        "_utc_time",
        "_finite_nonnegative",
        "_advisory_live_slot_outlook",
        "_observed_foxess_soc",
    }
    module = ast.Module(
        body=[
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ],
        type_ignores=[],
    )
    context: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
    }
    exec(compile(ast.fix_missing_locations(module), str(SLOTS), "exec"), context)
    return context


def _slot(start: datetime) -> dict[str, Any]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": 29.56,
        "label": start.strftime("%H:%M"),
    }


def test_priority_event_still_displays_plan_without_inventing_soc() -> None:
    helper = _helpers()["_advisory_live_slot_outlook"]
    now = datetime.now(UTC)
    start = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    today_slots = [_slot(start), _slot(start + timedelta(minutes=30))]
    state = {
        "rolling_export_plan": {
            "available": True,
            "generated_at": now.isoformat(),
            "planning_soc_percent": 70.0,
            "planning_soc_source": "settled current-day digital-twin SOC",
            "physical_planning_evidence": {"available": False},
            "selected_slots": [
                {
                    **today_slots[1],
                    "planned_battery_export_kwh": 2.1,
                    "planned_battery_to_home_kwh": 0.4,
                }
            ],
        },
        "power_down_priority": {
            "joined": True,
            "active": True,
            "start": today_slots[0]["valid_from"],
            "end": today_slots[1]["valid_to"],
        },
        "today_slots": today_slots,
    }
    outlook = helper(state)
    assert outlook
    assert any("Power Down priority" in row["action"] for row in outlook.values())
    assert all(row["estimated_soc_percent"] is None for row in outlook.values())
    assert all(row["reporting_only"] is True for row in outlook.values())
    assert all(row["advisory"] is True for row in outlook.values())


def test_normal_agile_schedule_also_falls_back_to_planned_actions() -> None:
    helper = _helpers()["_advisory_live_slot_outlook"]
    now = datetime.now(UTC)
    start = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    slot = _slot(start + timedelta(minutes=30))
    state = {
        "rolling_export_plan": {
            "available": True,
            "generated_at": now.isoformat(),
            "physical_planning_evidence": {"available": False},
            "selected_slots": [
                {
                    **slot,
                    "planned_battery_export_kwh": 2.4,
                    "planned_battery_to_home_kwh": 0.3,
                }
            ],
        },
        "today_slots": [slot],
        "power_down_priority": {"joined": False},
    }
    rows = helper(state)
    assert rows[slot["valid_from"]]["action"] == "Agile battery export planned"
    assert rows[slot["valid_from"]]["estimated_soc_percent"] is None
    state["rolling_export_plan"]["generated_at"] = (
        now - timedelta(minutes=8)
    ).isoformat()
    assert helper(state) == {}
    state["rolling_export_plan"]["available"] = False
    assert helper(state) == {}


def test_fresh_observed_soc_is_separate_from_future_projection() -> None:
    observed = _helpers()["_observed_foxess_soc"]
    now = datetime.now(UTC)
    snap = SimpleNamespace(
        timestamp=now,
        battery_soc=64.0,
        stale_fields=[],
        source_age_seconds={"battery_soc": 20.0},
    )
    coordinator = SimpleNamespace(
        data=SimpleNamespace(snapshot=snap),
        settings=SimpleNamespace(control=SimpleNamespace(stale_data_seconds=180.0)),
    )
    assert observed(coordinator) == 64.0
    snap.source_age_seconds["battery_soc"] = 185.0
    assert observed(coordinator) is None
    snap.source_age_seconds["battery_soc"] = 20.0
    snap.stale_fields = ("battery_soc",)
    assert observed(coordinator) is None
    snap.stale_fields = ()
    snap.timestamp = now - timedelta(minutes=3)
    assert observed(coordinator) is None
    snap.timestamp = now
    snap.battery_soc = 127.0
    assert observed(coordinator) is None
    assert observed(SimpleNamespace(data=None)) is None


def test_dashboard_references_advisory_plans_without_simulated_soc_fallback() -> None:
    source = DASH.read_text()
    assert "published_plan_slot_outlook" in source
    assert "observed_foxess_soc_percent" in source
    assert "Power Down" in source
    assert "physical_live_slot_outlook_current_soc_percent" in source
    assert "Physical SOC path unavailable — see Agile Plan" not in source
    assert "_Live SOC outlook uses verified physical" not in source
    assert "simulated SOC" in source


def test_release_version_and_physical_control_stays_separate() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.159"
    slots = SLOTS.read_text()
    assert '"physical_live_slot_outlook_available": bool(live_outlook)' in slots
    assert "advisory_outlook = _advisory_live_slot_outlook" in slots
    assert '"hardware_writes": "blocked"' in slots
    assert "services.async_call(" not in slots
