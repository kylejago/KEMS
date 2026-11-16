"""Alpha9.211 read-only Happy Hour counter and historical evidence tests."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _module(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(
        "alpha9211_" + path.stem, path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state(state: str, unit: str = "kWh", state_class: str = "total_increasing"):
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    return SimpleNamespace(
        state=state,
        attributes={"unit_of_measurement": unit, "state_class": state_class},
        last_reported=now - timedelta(seconds=8),
        last_updated=now - timedelta(minutes=3),
    )


def _registry(device: str = "foxess-kh7", disabled=None):
    return SimpleNamespace(
        device_id=device, config_entry_id="foxess-modbus", disabled_by=disabled
    )


def test_potential_cumulative_kh7_meter_never_authorises_free_import() -> None:
    probe = _module("kems_core/operational_diagnostic_probes.py")
    status = probe.foxess_import_counter_candidate_probe(
        source_entity_id="sensor.kh7_grid_consumption",
        source_registry=_registry(),
        candidates={
            "lifetime_total": (_registry(), _state("1234.567")),
            "daily_total": (_registry(), _state("7.123", state_class="total")),
        },
        now=datetime(2026, 11, 16, 12, tzinfo=UTC),
    )
    assert status["reporting_only"] is True
    assert status["counter_source_approved"] is False
    assert status["long_gap_recovery_enabled"] is False
    assert status["reward_hour_cap_kwh"] == 16
    first = status["candidates"]["lifetime_total"]
    assert first["candidate_status"] == "single_reading_only_unverified"
    assert first["observed_kwh"] == 1234.567
    assert first["source_device_match"] is True
    assert first["age_seconds"] == 8
    assert status["candidates"]["daily_total"]["observed_kwh"] == 7.123


@pytest.mark.parametrize(
    ("state", "unit", "klass", "device", "expected"),
    [
        ("unavailable", "kWh", "total", "foxess-kh7", "unavailable"),
        ("unknown", "kWh", "total", "foxess-kh7", "unavailable"),
        ("-1", "kWh", "total", "foxess-kh7", "invalid_or_non_numeric"),
        ("nan", "kWh", "total", "foxess-kh7", "invalid_or_non_numeric"),
        ("7.0", "W", "total", "foxess-kh7", "not_kwh"),
        ("7.0", "kWh", "measurement", "foxess-kh7", "not_cumulative_state_class"),
        ("7.0", "kWh", "total", "different", "different_registry_device_or_entry"),
    ],
)
def test_meter_probe_fails_closed_on_ineligible_candidate(
    state, unit, klass, device, expected
) -> None:
    probe = _module("kems_core/operational_diagnostic_probes.py")
    result = probe.foxess_import_counter_candidate_probe(
        source_entity_id="sensor.kh7_grid_consumption",
        source_registry=_registry(),
        candidates={"lifetime_total": (_registry(device), _state(state, unit, klass))},
        now=datetime(2026, 11, 16, 12, tzinfo=UTC),
    )
    row = result["candidates"]["lifetime_total"]
    assert row["candidate_status"] == expected
    assert row["restart_delta_usable"] is False


def test_missing_and_disabled_candidate_not_mistaken_for_proven_meter() -> None:
    probe = _module("kems_core/operational_diagnostic_probes.py")
    result = probe.foxess_import_counter_candidate_probe(
        source_entity_id="sensor.kh7_grid_consumption",
        source_registry=_registry(),
        candidates={
            "lifetime_total": (None, None),
            "daily_total": (_registry(disabled="integration"), None),
        },
        now=datetime(2026, 11, 16, 12, tzinfo=UTC),
    )
    assert result["candidates"]["lifetime_total"]["candidate_status"] == "not_registered"
    assert result["candidates"]["daily_total"]["candidate_status"] == "disabled"
    assert result["counter_source_approved"] is False


def test_second_november_hour_reports_47_6_minutes_and_recovery_limit() -> None:
    accounting = _module("happy_hour_accounting_diagnostics.py")
    start = "2026-11-01T13:00:00+00:00"
    end = "2026-11-01T14:00:00+00:00"
    audit = {
        "entries_omitted": 0,
        "included_happy_hour_pence": 378.333,
        "provisional_partial_pence": 116.604,
        "entries": [
            {
                "type": "happy_hour",
                "start": start,
                "end": end,
                "event_id": "8068",
                "booking_source": "octopus_joined_events",
                "included_in_roi": True,
                "estimated_reward_pence": 116.604,
                "evidence_source": "provisional_partial_meter_credit",
                "covered_minutes": 47.6,
                "coverage_percent": 79.333,
                "status": "included_provisional_partial_estimate",
            }
        ],
    }
    old = deepcopy(audit)
    persisted = {
        "first_sample": "2026-11-15T06:51:30+00:00",
        "last_sample": "2026-11-15T09:09:02+00:00",
    }
    output = accounting.build_happy_hour_accounting_audit(
        persisted, [], roi_reward_audit=audit
    )
    row = output["hour_evidence"][0]
    assert row["event_id"] == "8068"
    assert row["independent_booking_recorded"] is True
    assert row["roi_estimated_credit_pence"] == 116.604
    assert row["saved_credit_pence"] is None
    assert row["observed_minutes"] == 47.6
    assert row["missing_unverified_minutes"] == 12.4
    assert row["on_device_recovery_status"] == (
        "unrecoverable_from_current_on_device_store"
    )
    assert output["hours_outside_current_meter_store"] == 1
    assert output["provisional_roi_hours_without_complete_receipt"] == 1
    assert output["supplier_credit_settled"] is False
    assert audit == old


def test_full_hour_receipt_not_duplicated_and_store_overlap_not_authority() -> None:
    accounting = _module("happy_hour_accounting_diagnostics.py")
    start = "2026-11-15T07:00:00+00:00"
    end = "2026-11-15T08:00:00+00:00"
    persisted = {
        "first_sample": "2026-11-15T06:51:30+00:00",
        "last_sample": "2026-11-15T09:09:02+00:00",
        "persisted_reward_windows": [{
            "start": start, "end": end,
            "event_id": "8546", "booking_source": "octopus_joined_events"
        }],
    }
    receipt = {
        "start": start, "end": end, "completed": True,
        "credit_pence": 255.521419, "import_kwh": 7.121
    }
    audit = {
        "entries": [{
            "type": "happy_hour", "start": start, "end": end,
            "included_in_roi": True, "estimated_reward_pence": 255.521,
            "evidence_source": "completed_meter_and_tariff_verified_hour"
        }],
        "entries_omitted": 0,
        "included_happy_hour_pence": 255.521419,
        "provisional_partial_pence": 0.0,
    }
    result = accounting.build_happy_hour_accounting_audit(
        persisted, [receipt], roi_reward_audit=audit
    )
    assert len(result["hour_evidence"]) == 1
    assert result["completed_verified_receipts"] == 1
    assert result["provisional_roi_hours_without_complete_receipt"] == 0
    assert result["roi_reconciliation"]["status"] == "reconciled_estimate_tiers"


def test_unknown_meter_store_does_not_claim_irrecoverable() -> None:
    accounting = _module("happy_hour_accounting_diagnostics.py")
    value = accounting._meter_window_recovery(
        datetime(2026, 11, 1, 13, tzinfo=UTC),
        datetime(2026, 11, 1, 14, tzinfo=UTC),
        {},
    )
    assert value == "on_device_meter_range_unknown"


def test_diagnostic_wiring_is_read_only_without_new_control_authority() -> None:
    source = (ROOT / "diagnostics.py").read_text()
    assert "happy_hour_import_counter_candidates" in source
    assert "foxess_import_counter_candidate_probe" in source
    assert "unrecoverable_from_current_on_device_store" in (
        ROOT / "happy_hour_accounting_diagnostics.py"
    ).read_text()
    assert "async_update_entity" not in source
