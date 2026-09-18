"""Alpha9.58 battery-direction commissioning evidence regressions."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kems_core.commissioning_evidence import (
    BatteryDirectionObservation,
    assess_battery_power_direction,
)

ROOT = Path(__file__).resolve().parents[1]
COMMISSIONING = ROOT / "custom_components" / "kems" / "commissioning.py"
SESSION = ROOT / "custom_components" / "kems" / "commissioning_session.py"

_SESSION_SPEC = importlib.util.spec_from_file_location(
    "kems_alpha958_commissioning_session",
    SESSION,
)
assert _SESSION_SPEC is not None and _SESSION_SPEC.loader is not None
_SESSION_MODULE = importlib.util.module_from_spec(_SESSION_SPEC)
_SESSION_SPEC.loader.exec_module(_SESSION_MODULE)
collect_battery_direction_records = _SESSION_MODULE.collect_battery_direction_records


def _observation(
    at: datetime,
    *,
    power_kw: float,
    soc: float = 63.0,
    remaining_kwh: float | None = None,
    charge_today_kwh: float | None = None,
    discharge_today_kwh: float | None = None,
) -> BatteryDirectionObservation:
    return BatteryDirectionObservation(
        timestamp=at,
        battery_power_kw=power_kw,
        battery_soc=soc,
        battery_energy_remaining_kwh=remaining_kwh,
        battery_charge_today_kwh=charge_today_kwh,
        battery_discharge_today_kwh=discharge_today_kwh,
    )


def test_bms_remaining_energy_proves_direction_without_whole_percent_soc_change() -> (
    None
):
    start = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    records = [
        _observation(start, power_kw=-1.0, remaining_kwh=30.000),
        _observation(
            start + timedelta(minutes=1),
            power_kw=-1.0,
            remaining_kwh=30.010,
        ),
        _observation(
            start + timedelta(minutes=2),
            power_kw=-1.0,
            remaining_kwh=30.020,
        ),
    ]

    evidence = assess_battery_power_direction(records)

    assert evidence.ready is True
    assert evidence.positive_is_discharge is True
    assert evidence.evidence_samples == 2
    assert evidence.confidence_percent == 100.0
    assert dict(evidence.basis_counts)["bms_energy_remaining"] == 2
    assert dict(evidence.basis_counts)["soc"] == 0


def test_daily_discharge_counter_is_valid_fallback_direction_evidence() -> None:
    start = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    records = [
        _observation(
            start,
            power_kw=1.2,
            remaining_kwh=None,
            charge_today_kwh=4.0,
            discharge_today_kwh=5.000,
        ),
        _observation(
            start + timedelta(minutes=1),
            power_kw=1.2,
            remaining_kwh=None,
            charge_today_kwh=4.0,
            discharge_today_kwh=5.010,
        ),
        _observation(
            start + timedelta(minutes=2),
            power_kw=1.2,
            remaining_kwh=None,
            charge_today_kwh=4.0,
            discharge_today_kwh=5.020,
        ),
    ]

    evidence = assess_battery_power_direction(records)

    assert evidence.ready is True
    assert evidence.positive_is_discharge is True
    assert dict(evidence.basis_counts)["daily_energy_counters"] == 2


def test_soc_remains_fail_closed_fallback_when_energy_sources_do_not_move() -> None:
    start = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    records = [
        _observation(start, power_kw=-0.3, soc=63.0, remaining_kwh=30.0),
        _observation(
            start + timedelta(minutes=1),
            power_kw=-0.3,
            soc=63.0,
            remaining_kwh=30.0,
        ),
    ]

    evidence = assess_battery_power_direction(records)

    assert evidence.ready is False
    assert evidence.state == "collecting"
    assert evidence.evidence_samples == 0
    assert evidence.positive_is_discharge is None


def test_direction_session_resets_on_auxiliary_source_signature_change() -> None:
    owner = SimpleNamespace()
    start = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    first = (("battery_energy_remaining_kwh", "sensor.bms|kWh"),)
    changed = (("battery_energy_remaining_kwh", "sensor.bms_new|kWh"),)

    collect_battery_direction_records(
        owner,
        source_signature=first,
        record=_observation(start, power_kw=-1.0, remaining_kwh=30.0),
        ready=True,
    )
    records, metadata = collect_battery_direction_records(
        owner,
        source_signature=changed,
        record=_observation(
            start + timedelta(minutes=1),
            power_kw=-1.0,
            remaining_kwh=30.01,
        ),
        ready=True,
    )

    assert len(records) == 1
    assert metadata["reset_reason"] == "source_signature_changed"
    assert metadata["persistent"] is False


def test_commissioning_prefers_energy_evidence_but_retains_soc_fallback() -> None:
    source = COMMISSIONING.read_text(encoding="utf-8")

    assert "collect_battery_direction_records" in source
    assert "assess_battery_power_direction" in source
    assert "_bms_kwh_remaining" in source
    assert "_battery_charge_today" in source
    assert "_battery_discharge_today" in source
    assert "then daily charge/discharge counters, then SOC" in source
    assert '"foxess_battery_direction_evidence"' in source
    assert '"foxess_battery_direction_session"' in source
