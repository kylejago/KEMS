"""Supplier charges and completed-event evidence are independent of live control."""

from datetime import UTC, datetime, timedelta

from kems_core.supplier_charges import (
    SupplierChargeEvidence,
    capture_completed_baseline,
    completed_power_down_estimate,
)
from kems_core.supplier_intervals import SupplierIntervalLedger

NOW = datetime(2026, 11, 27, tzinfo=UTC)
START = NOW - timedelta(days=2)


def _row(start, kind="electricity_import", kwh=1.0, charge=6.6):
    return {
        "kind": kind,
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "kwh": kwh,
        "charge_pence": charge,
    }


def _day(start, kind="electricity_import", count=48):
    return [_row(start + timedelta(minutes=30 * n), kind) for n in range(count)]


def _compare(charges, energy, commission="2026-11-24"):
    return charges.reconciliation(
        energy,
        {"2026-11-25": {"import_cost_pence": 300.0}},
        now=NOW,
        commissioning_date=commission,
    )


def test_matched_complete_priced_day_is_read_only_and_restart_safe():
    energy = SupplierIntervalLedger()
    charges = SupplierChargeEvidence()
    rows = _day(START)
    energy.ingest(rows, source="octopus_csv", now=NOW)
    assert charges.ingest(rows, source="octopus_csv", now=NOW)
    assert not charges.ingest(rows, source="octopus_csv", now=NOW)
    before = energy.dump()
    result = _compare(charges, energy)
    data = result["kinds"]["electricity_import"]
    assert data["complete_priced_post_commissioning_days"] == 1
    assert data["difference_pence"] == 16.8
    assert result["roi_or_ledger_write_authorised"] is False
    assert result["standing_charges_and_event_rewards_excluded"] is True
    assert energy.dump() == before
    restored = SupplierChargeEvidence()
    restored.restore(charges.dump(), now=NOW)
    assert _compare(restored, energy) == result
    assert _compare(charges, energy, commission="2026-11-25")["kinds"][
        "electricity_import"
    ]["complete_priced_post_commissioning_days"] == 0
    assert _compare(charges, energy, commission=None)["kinds"][
        "electricity_import"
    ]["complete_priced_post_commissioning_days"] == 0


def test_missing_energy_or_pricing_and_conflict_withhold_day():
    energy = SupplierIntervalLedger()
    charges = SupplierChargeEvidence()
    rows = _day(START)
    energy.ingest(rows[:-1], source="octopus_csv", now=NOW)
    charges.ingest(rows, source="octopus_csv", now=NOW)
    assert _compare(charges, energy)["kinds"]["electricity_import"][
        "complete_priced_post_commissioning_days"
    ] == 0
    energy.ingest(rows[-1:], source="octopus_csv", now=NOW)
    charges.ingest(
        [{**rows[0], "charge_pence": 7.6}], source="octopus_integration", now=NOW
    )
    assert _compare(charges, energy)["unmatched_or_conflicted_intervals"] == 1
    assert _compare(charges, energy)["kinds"]["electricity_import"][
        "complete_priced_post_commissioning_days"
    ] == 0


def test_late_baseline_survives_until_both_meter_windows_are_available():
    end = START + timedelta(hours=1)
    event = {
        "available": True,
        "session_id": "test",
        "session_start": START.isoformat(),
        "session_end": end.isoformat(),
    }
    baseline = {
        "baselines": [
            {
                "start": (START + timedelta(minutes=30 * n)).isoformat(),
                "end": (START + timedelta(minutes=30 * (n + 1))).isoformat(),
                "baseline": 0.5,
                "is_incomplete_calculation": False,
            }
            for n in range(2)
        ],
        "total_baseline": 1.0,
    }
    captured = capture_completed_baseline(
        event, baseline, baseline, now=NOW, points_per_kwh=800
    )
    assert captured is not None
    energy = SupplierIntervalLedger()
    assert completed_power_down_estimate(energy, captured)["estimated_bonus_pence"] is None
    imports = [_row(START + timedelta(minutes=30 * n), kwh=0.0, charge=0.0) for n in range(2)]
    exports = [_row(START + timedelta(minutes=30 * n), "electricity_export", 2.0) for n in range(2)]
    energy.ingest(imports, source="octopus_csv", now=NOW)
    assert completed_power_down_estimate(energy, captured)["estimated_bonus_pence"] is None
    energy.ingest(exports, source="octopus_csv", now=NOW)
    estimate = completed_power_down_estimate(energy, captured)
    assert estimate["estimated_bonus_pence"] == 400.0
    assert estimate["supplier_settled"] is False
    assert estimate["roi_or_ledger_write_authorised"] is False
    assert completed_power_down_estimate(
        energy, {**captured, "octopoints_per_kwh": None}
    )["estimated_bonus_pence"] is None
    energy.ingest([{**exports[0], "kwh": 3.0}], source="octopus_csv", now=NOW)
    assert completed_power_down_estimate(energy, captured)["estimated_bonus_pence"] is None
    assert capture_completed_baseline(event, baseline, {}, now=NOW) is None
    assert capture_completed_baseline(
        event,
        baseline,
        {**baseline, "baselines": baseline["baselines"][:1]},
        now=NOW,
    ) is None
