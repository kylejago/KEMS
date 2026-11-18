"""Alpha9.226: structured Ohme charger plans can only be diagnostic evidence."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
PARSER = ROOT / "kems_core" / "ohme_charge_slot_plan.py"


def _load():
    spec = importlib.util.spec_from_file_location("alpha9226_ohme_plan", PARSER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ohme_structured_extra_slot_matches_owner_17_nov_trace_not_tariff():
    mod = _load()
    now = datetime(2026, 11, 17, 6, 53, tzinfo=UTC)
    data = mod.observe_ohme_slot_response(
        {
            "slots": [
                {
                    "start": "2026-11-17T06:51:00",
                    "end": "2026-11-17T07:00:00",
                    "power": 3001,
                    "energy": 450,
                },
                {
                    "start": "2026-11-17T06:30:00",
                    "end": "2026-11-17T06:50:00",
                    "power": 3000,
                    "energy": 1000,
                },
            ]
        },
        now=now,
        timezone="Europe/London",
    )
    assert data["status"] == "plan_observed"
    assert data["valid_count"] == 2
    assert data["active_count"] == 1
    assert data["expired_count"] == 1
    assert data["slots"][1]["active_at_observation"] is True
    assert data["slots"][1]["power_kw"] == 3.001
    assert data["slots"][1]["energy_kwh"] == 0.45
    assert data["naive_timestamps_assumed_local"] == 2
    assert data["discount_authority"] is False


def test_past_and_overlapping_rescheduled_slots_do_not_become_cheap():
    mod = _load()
    now = datetime(2026, 11, 17, 7, 2, tzinfo=UTC)
    result = mod.observe_ohme_slot_response(
        {
            "slots": [
                {
                    "start": "2026-11-17T06:30:00+00:00",
                    "end": "2026-11-17T06:50:00+00:00",
                    "power": 3000,
                    "energy": 1000,
                },
                {
                    "start": "2026-11-17T06:30:00+00:00",
                    "end": "2026-11-17T06:50:00+00:00",
                    "power": 3000,
                    "energy": 1000,
                },
                {
                    "start": "2026-11-17T06:41:00+00:00",
                    "end": "2026-11-17T06:43:00+00:00",
                    "power": 3000,
                    "energy": 100,
                },
            ]
        },
        now=now,
    )
    assert result["valid_count"] == 2
    assert result["duplicate_count"] == 1
    assert result["overlap_count"] == 1
    assert result["active_count"] == 0
    assert result["expired_count"] == 2
    assert result["discount_authority"] is False


def test_invalid_undated_and_unbounded_plan_values_are_rejected():
    mod = _load()
    now = datetime(2026, 11, 18, 3, 49, tzinfo=UTC)
    rows = [
        {"start": "06:30", "end": "07:00", "power": 3000, "energy": 1500},
        {"start": "unknown", "end": "unavailable"},
        {
            "start": "2026-11-18T07:00:00+00:00",
            "end": "2026-11-18T06:30:00+00:00",
        },
        {
            "start": "2026-11-18T01:00:00+00:00",
            "end": "2026-11-18T02:00:00+00:00",
            "power": float("nan"),
        },
    ]
    result = mod.observe_ohme_slot_response({"slots": rows}, now=now)
    assert result["status"] == "plan_observed"
    assert result["valid_count"] == 1
    assert result["invalid_count"] == 3
    assert result["slots"][0]["power_kw"] is None
    assert result["discount_authority"] is False


def test_empty_unknown_and_malformed_responses_never_authorise_anything():
    mod = _load()
    now = datetime(2026, 11, 18, 3, 49, tzinfo=UTC)
    for response in (None, "unknown", {"slots": "unavailable"}):
        output = mod.observe_ohme_slot_response(response, now=now)
        assert output["status"] == "unexpected_response"
        assert output["active_count"] == 0
        assert output["discount_authority"] is False
    empty = mod.observe_ohme_slot_response({"slots": []}, now=now)
    assert empty["status"] == "no_slots_reported"


def test_dst_aware_and_naive_fields_preserve_distinct_slots():
    mod = _load()
    now = datetime(2026, 10, 25, 1, 35, tzinfo=UTC)
    result = mod.observe_ohme_slot_response(
        {
            "slots": [
                {
                    "start": "2026-10-25T01:10:00+01:00",
                    "end": "2026-10-25T01:20:00+01:00",
                },
                {
                    "start": "2026-10-25T01:10:00+00:00",
                    "end": "2026-10-25T01:20:00+00:00",
                },
            ]
        },
        now=now,
    )
    assert result["valid_count"] == 2
    assert result["expired_count"] == 2


def test_observer_is_independent_from_coordinator_control_and_uses_read_only_api():
    obs = (ROOT / "ohme_charge_slot_observer.py").read_text()
    coordinator = (ROOT / "coordinator.py").read_text()
    diag = (ROOT / "diagnostics.py").read_text()
    assert '"list_charge_slots"' in obs
    assert '"set_price_cap"' not in obs
    assert '"set_mode"' not in obs
    assert "POLL_INTERVAL_SECONDS = 90" in obs
    assert "PLAN_FRESH_SECONDS = 180" in obs
    assert "await self._ohme_charge_plan.async_setup()" in coordinator
    assert "await self._ohme_charge_plan.async_shutdown()" in coordinator
    assert '"ohme_charge_plan_observer"' in diag
    assert "self._ohme_charge_plan" not in (ROOT / "tariff.py").read_text()
    assert "self._ohme_charge_plan" not in (ROOT / "commissioning.py").read_text()
    for source in (obs, coordinator, diag):
        ast.parse(source)
