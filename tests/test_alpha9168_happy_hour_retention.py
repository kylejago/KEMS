"""Regression for Alpha9.169: completed Happy Hour physical evidence retention.

The 1 November 2026 reward ended at 14:00; by 21:18 the old six-hour
in-memory retention had silently deleted BOTH completed-hour confirmations.
The persisted HA Store had last been written during the reward, so a guarded
restart the following morning can recover that evidence with longer retention.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from kems_core.happy_hour_financial import estimate_happy_hour_credit

SOURCE = (
    Path(__file__).parents[1]
    / "custom_components"
    / "kems"
    / "happy_hour_import_ledger.py"
)


class _FakeStore:
    def __init__(self, hass: Any, version: int, key: str) -> None:
        self.hass = hass
        self.key = key

    async def async_load(self) -> dict[str, Any] | None:
        return self.hass.data.get(self.key)

    async def async_save(self, data: dict[str, Any]) -> None:
        self.hass.data[self.key] = data


class _FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}


def _recorder_class():
    """Load the pure recorder body without importing Home Assistant in CI."""
    root = ast.parse(SOURCE.read_text(encoding="utf-8"))
    allowed = {
        "_STORAGE_VERSION",
        "_PRE_EVENT_SEED",
        "_POST_EVENT_EVIDENCE_GRACE",
        "_RETENTION",
        "_MAX_SAMPLES",
        "_MAX_METER_AGE_SECONDS",
        "_MAX_SNAPSHOT_CLOCK_SKEW_SECONDS",
        "_utc",
        "_number",
        "GridImportReading",
        "HappyHourImportLedgerRecorder",
    }
    nodes = [
        node
        for node in root.body
        if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in allowed)
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in allowed
                for target in node.targets
            )
        )
    ]
    ns = {
        "__name__": "test_alpha9168_happy_hour_retention",
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "isfinite": isfinite,
        "Any": Any,
        "dataclass": dataclass,
        "Store": _FakeStore,
        "DOMAIN": "kems",
        "STORAGE_NAMESPACE": "regression",
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns["HappyHourImportLedgerRecorder"], ns["_RETENTION"]


def test_pre_168_verified_store_survives_next_morning_restart() -> None:
    """Recover the original full session evidence without any live booking."""
    Recorder, retention = _recorder_class()
    assert retention >= timedelta(days=2)
    hass = _FakeHass()
    anchor = datetime.now(UTC)
    # Yesterday's two-hour Happy Hour at least 16 hours before this restart.
    start = (anchor - timedelta(hours=18)).replace(microsecond=0)
    middle = start + timedelta(hours=1)
    end = middle + timedelta(hours=1)
    recorder = Recorder(hass, "user-entry", grid_import_entity="sensor.site_import")
    store = recorder._store
    hass.data[store.key] = {
        "source_entity": "sensor.site_import",
        "windows": [
            {"start": start.isoformat(), "end": middle.isoformat()},
            {"start": start.isoformat(), "end": end.isoformat()},
            {"start": middle.isoformat(), "end": end.isoformat()},
        ],
        "samples": [
            {
                "timestamp": (start + timedelta(minutes=i)).isoformat(),
                "grid_import_kw": 6.0,
            }
            for i in (1, 20, 40, 61, 80, 100)
        ],
    }
    before = hass.data[store.key]
    asyncio.run(recorder.async_load())
    assert recorder.status["load_status"] == "restored"
    assert recorder.status["retained_samples"] == 6
    assert len(recorder.status["persisted_reward_windows"]) == 3
    assert recorder.status["retention_days"] >= 2

    # No new live confirmed booking exists, so ledger cannot record new
    # physical readings or issue writes after a completed session.
    assert (
        asyncio.run(recorder.async_observe(object(), now=anchor, confirmed_windows=[]))
        is False
    )
    assert hass.data[store.key] is before

    # Financial-only reconstruction uses the retained exact one-hour windows;
    # a merged two-hour window is NOT a third reward allowance.
    hours = [
        {
            "start": st.isoformat(),
            "end": en.isoformat(),
            "import_kwh": kwh,
            "cap_kwh": 16.0,
            "coverage_complete": True,
        }
        for st, en, kwh in (
            (start, middle, 7.294),
            (middle, end, 3.655),
        )
    ]
    credit = estimate_happy_hour_credit(
        plan={"reward_hours": hours},
        bookings={"bookings": []},
        persisted_confirmed_windows=recorder.status["persisted_reward_windows"],
        now=anchor,
        import_rate_pence=35.8828,
        gross_import_cost_pence=739.72,
    )
    assert credit["credited_import_kwh"] == 10.949
    assert credit["estimated_credit_pence"] == 392.881
    assert credit["verified_reward_hours"] == 2


def test_source_rebinding_never_reuses_old_physical_meter_history() -> None:
    Recorder, _ = _recorder_class()
    hass = _FakeHass()
    recorder = Recorder(hass, "another-entry", grid_import_entity="sensor.new")
    hass.data[recorder._store.key] = {
        "source_entity": "sensor.old",
        "samples": [
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "grid_import_kw": 3.0,
            }
        ],
        "windows": [],
    }
    asyncio.run(recorder.async_load())
    assert recorder.status["load_status"] == "different_meter_source"
    assert recorder.status["retained_samples"] == 0
    assert recorder.status["persisted_reward_windows"] == []


def test_retention_still_bounded_and_expires_old_evidence() -> None:
    Recorder, retention = _recorder_class()
    hass = _FakeHass()
    recorder = Recorder(hass, "old", grid_import_entity="sensor.site_import")
    now = datetime.now(UTC)
    old_end = now - retention - timedelta(hours=1)
    hass.data[recorder._store.key] = {
        "source_entity": "sensor.site_import",
        "samples": [
            {
                "timestamp": (old_end - timedelta(minutes=15)).isoformat(),
                "grid_import_kw": 2.0,
            }
        ],
        "windows": [
            {
                "start": (old_end - timedelta(hours=1)).isoformat(),
                "end": old_end.isoformat(),
            }
        ],
    }
    asyncio.run(recorder.async_load())
    assert recorder.status["retained_samples"] == 0
    assert recorder.status["persisted_reward_windows"] == []
