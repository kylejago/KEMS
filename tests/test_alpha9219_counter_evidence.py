"""Alpha9.220: restart-persistent counter evidence, never speculative recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core.counter_evidence import (
    CounterEvidenceSeries,
    counter_observation,
)
from kems_core.period_coverage_probe import observation_coverage_probe


def _ha_state(
    kwh: float | str,
    timestamp: datetime,
    *,
    unit: str = "kWh",
    state_class: str = "total",
) -> SimpleNamespace:
    return SimpleNamespace(
        state=str(kwh),
        attributes={"unit_of_measurement": unit, "state_class": state_class},
        last_reported=timestamp,
        last_updated=timestamp,
    )


class _Hass:
    def __init__(self, **states: SimpleNamespace):
        self.states = SimpleNamespace(get=lambda name: states.get(name))


def test_stale_derived_counter_is_not_accepted_for_backfill() -> None:
    now = datetime(2026, 11, 17, 14, tzinfo=UTC)
    row, reason = counter_observation(
        label="lifetime_total",
        entity_id="sensor.kh7_grid_consumption_energy_total",
        state=_ha_state(2073.9, now - timedelta(seconds=8981)),
        now=now,
    )
    assert row is None
    assert reason == "stale_counter_report"
    log = CounterEvidenceSeries("sensor.kh7_grid_consumption")
    log.observe(
        _Hass(
            **{
                "sensor.kh7_grid_consumption_energy_total": _ha_state(
                    2073.9, now - timedelta(seconds=8981)
                )
            }
        ),
        now=now,
    )
    status = log.status()
    assert status["candidates"]["lifetime_total"]["fresh_report_samples"] == 0
    assert status["backfill_approved"] is False
    assert status["refund_or_roi_credit_authority"] is False


def test_fresh_sequence_tracks_monotonicity_without_physical_authority() -> None:
    now = datetime(2026, 11, 17, 0, tzinfo=UTC)
    entity = "sensor.kh7_grid_consumption_energy_total"
    series = CounterEvidenceSeries("sensor.kh7_grid_consumption")
    for minutes, kwh in [(0, 100.0), (16, 100.25), (32, 100.5)]:
        at = now + timedelta(minutes=minutes)
        assert series.observe(_Hass(**{entity: _ha_state(kwh, at)}), now=at)
    # A report arriving too soon must not flood the bounded Store.
    at = now + timedelta(minutes=33)
    assert not series.observe(_Hass(**{entity: _ha_state(100.6, at)}), now=at)
    status = series.status()
    lifetime = status["candidates"]["lifetime_total"]
    assert lifetime["fresh_report_samples"] == 3
    assert lifetime["nonnegative_plausible_delta_pairs"] == 2
    assert lifetime["positive_plausible_delta_kwh"] == 0.5
    assert lifetime["restart_gap_delta_usable"] is False
    assert lifetime["physical_meter_provenance_verified"] is False


def test_source_identity_and_tampered_records_rejected_on_restore() -> None:
    now = datetime(2026, 11, 17, 14, tzinfo=UTC)
    row = {
        "label": "lifetime_total",
        "entity_id": "sensor.source_energy_total",
        "observed_at": now.isoformat(),
        "reported_at": now.isoformat(),
        "kwh": 50.0,
    }
    evidence = CounterEvidenceSeries("sensor.source")
    evidence.restore(
        {
            "source_entity_id": "sensor.another_source",
            "candidates": {"lifetime_total": [row]},
        },
        now=now,
    )
    assert (
        evidence.status()["candidates"]["lifetime_total"]["fresh_report_samples"] == 0
    )
    evidence.restore(
        {
            "source_entity_id": "sensor.source",
            "candidates": {
                "lifetime_total": [
                    row,
                    {**row, "kwh": float("nan")},
                    {**row, "reported_at": "not a timestamp"},
                ]
            },
        },
        now=now,
    )
    assert (
        evidence.status()["candidates"]["lifetime_total"]["fresh_report_samples"] == 1
    )
    reloaded = CounterEvidenceSeries("sensor.source")
    reloaded.restore(evidence.payload(), now=now + timedelta(minutes=1))
    assert reloaded.payload() == evidence.payload()


def test_counter_resets_and_impossible_spikes_are_not_validated() -> None:
    now = datetime(2026, 11, 17, 0, tzinfo=UTC)
    series = CounterEvidenceSeries("sensor.source")
    entity = "sensor.source_energy_today"
    for minutes, value in [(0, 4.2), (16, 4.6), (32, 0.1), (48, 100.0)]:
        at = now + timedelta(minutes=minutes)
        assert series.observe(_Hass(**{entity: _ha_state(value, at)}), now=at)
    info = series.status()["candidates"]["daily_total"]
    assert info["nonnegative_plausible_delta_pairs"] == 1
    assert info["reset_or_decrease_pairs"] == 1
    assert info["implausible_delta_pairs"] == 1
    assert info["restart_gap_delta_usable"] is False


def _snapshot(when: datetime, load: float | None = 1.0):
    return SimpleNamespace(
        timestamp=when,
        house_load_kw=load,
        grid_import_kw=0.1,
        grid_export_kw=0.0,
        current_import_rate=0.35,
        stale_fields=(),
        tariff_stale_fields=(),
    )


def test_forensic_gaps_report_exact_times_not_inferred_energy() -> None:
    start = datetime(2026, 11, 16, 8, tzinfo=UTC)
    records = [
        _snapshot(start),
        _snapshot(start + timedelta(minutes=5)),
        _snapshot(start + timedelta(minutes=22), load=None),
        _snapshot(start + timedelta(minutes=27)),
    ]
    result = observation_coverage_probe(records, start + timedelta(hours=3))
    gaps = result["source_gap_details"]
    assert gaps
    assert result["source_gap_details_available"] == len(gaps)
    interval = next(
        x for x in gaps if "observation_gap_over_10_minutes" in x["reasons"]
    )
    assert interval["start"] == records[1].timestamp.isoformat()
    assert interval["end"] == records[2].timestamp.isoformat()
    assert interval["duration_seconds"] == 1020
    assert interval["interval_kwh_proven"] is False
    assert interval["eligible_for_backfill"] is False
    assert result["gap_timestamps_are_not_cumulative_meter_anchors"] is True


def test_counter_time_and_unit_rejections() -> None:
    now = datetime(2026, 11, 17, 14, tzinfo=UTC)
    for state, expected in [
        (_ha_state(-1.0, now), "invalid_value"),
        (_ha_state(1.0, now, unit="W"), "wrong_unit"),
        (_ha_state(1.0, now, state_class="measurement"), "not_cumulative_class"),
        (_ha_state(1.0, now + timedelta(minutes=2)), "future_report_timestamp"),
    ]:
        _, reason = counter_observation(
            label="daily_total",
            entity_id="sensor.source_energy_today",
            state=state,
            now=now,
        )
        assert reason == expected
