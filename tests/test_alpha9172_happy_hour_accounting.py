"""Alpha9.172: booking proof is independent of physical meter sample freshness."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
        if self.hass.fail_save:
            raise OSError("Home Assistant store unavailable")
        self.hass.data[self.key] = data


class _FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.fail_save = False


def _recorder_class():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
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
    selected = [
        node
        for node in tree.body
        if (
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and node.name in allowed
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in allowed
                for target in node.targets
            )
        )
    ]
    ns = {
        "__name__": "test_alpha9172_happy_hour_accounting",
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
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns["HappyHourImportLedgerRecorder"]


def _booked_hours(now: datetime) -> list[dict[str, Any]]:
    start = now - timedelta(minutes=15)
    middle = start + timedelta(hours=1)
    end = middle + timedelta(hours=1)
    return [
        {
            "start": start.isoformat(),
            "end": middle.isoformat(),
            "event_id": "8067",
            "booking_source": "octopus_joined_events",
        },
        {
            "start": middle.isoformat(),
            "end": end.isoformat(),
            "event_id": "8068",
            "booking_source": "octopus_joined_events",
        },
    ]


def test_independent_confirmations_survive_a_stale_meter_and_restart() -> None:
    Recorder = _recorder_class()
    hass = _FakeHass()
    now = datetime.now(UTC).replace(microsecond=0)
    booked = _booked_hours(now)
    merged = {
        "start": booked[0]["start"],
        "end": booked[1]["end"],
        "event_id": "merged-two-hour-display",
    }
    recorder = Recorder(hass, "kems", grid_import_entity="sensor.site_import")

    # Meter unavailable precisely when joined-event confirmation is received.
    assert (
        asyncio.run(
            recorder.async_observe(
                object(), now=now, confirmed_windows=[merged, *booked]
            )
        )
        is False
    )
    stored = hass.data[recorder._store.key]
    assert len(stored["windows"]) == 2
    assert [row["event_id"] for row in stored["windows"]] == ["8067", "8068"]
    assert stored["samples"] == []

    restarted = Recorder(hass, "kems", grid_import_entity="sensor.site_import")
    asyncio.run(restarted.async_load())
    assert [row["event_id"] for row in restarted.status["persisted_reward_windows"]] == [
        "8067",
        "8068",
    ]
    # Bookings can expire; no fabricated meter readings or renewed commands.
    assert (
        asyncio.run(
            restarted.async_observe(object(), now=now, confirmed_windows=[])
        )
        is False
    )
    assert len(restarted.status["persisted_reward_windows"]) == 2


def test_one_hour_proof_needs_an_independent_joined_identity() -> None:
    Recorder = _recorder_class()
    hass = _FakeHass()
    now = datetime.now(UTC).replace(microsecond=0)
    hour = _booked_hours(now)[0]
    recorder = Recorder(hass, "kems", grid_import_entity="sensor.site_import")
    unconfirmed = {"start": hour["start"], "end": hour["end"]}
    assert (
        asyncio.run(
            recorder.async_observe(
                object(), now=now, confirmed_windows=[unconfirmed]
            )
        )
        is False
    )
    assert recorder.status["persisted_reward_windows"] == []
    assert recorder._store.key not in hass.data


def test_meter_proof_is_not_substituted_by_a_booking_or_a_stale_sample() -> None:
    Recorder = _recorder_class()
    hass = _FakeHass()
    now = datetime.now(UTC).replace(microsecond=0)
    recorder = Recorder(hass, "kems", grid_import_entity="sensor.site_import")
    booking = _booked_hours(now)[0]
    stale = SimpleNamespace(
        timestamp=now,
        grid_import_kw=7.0,
        source_age_seconds={"grid_import_kw": 90.0},
        stale_fields=(),
    )
    assert (
        asyncio.run(
            recorder.async_observe(stale, now=now, confirmed_windows=[booking])
        )
        is False
    )
    assert recorder.samples == []

    fresh = SimpleNamespace(
        timestamp=now + timedelta(seconds=10),
        grid_import_kw=6.0,
        source_age_seconds={"grid_import_kw": 0.0},
        stale_fields=(),
    )
    assert asyncio.run(
        recorder.async_observe(
            fresh, now=now + timedelta(seconds=10), confirmed_windows=[]
        )
    )
    assert len(recorder.samples) == 1
    assert len(hass.data[recorder._store.key]["windows"]) == 1


def test_failed_confirmation_write_is_not_claimed_as_persisted() -> None:
    Recorder = _recorder_class()
    hass = _FakeHass()
    hass.fail_save = True
    now = datetime.now(UTC).replace(microsecond=0)
    recorder = Recorder(hass, "kems", grid_import_entity="sensor.site_import")
    assert (
        asyncio.run(
            recorder.async_observe(
                object(), now=now, confirmed_windows=_booked_hours(now)
            )
        )
        is False
    )
    assert recorder.status["persisted_reward_windows"] == []
    assert recorder.samples == []


def test_accounting_recorder_call_does_not_pass_merged_display_windows() -> None:
    coordinator = (
        Path(__file__).parents[1] / "custom_components" / "kems" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert "confirmed_windows=[*independent_hours, *external_hours]" in coordinator
    assert "*joined_windows," not in coordinator
    assert "*external_windows," not in coordinator
