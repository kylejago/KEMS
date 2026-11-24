"""Guard-owned SOC provenance and exact settled-summary reuse."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from kems_core.agile_historical_replay_cache import HistoricalReplayCache
from kems_core.diagnostic_evidence import agile_current_export_execution_observation


def test_new_anchor_uses_guard_scan_not_advisory_timestamp():
    now = datetime(2026, 11, 24, 21, 52, tzinfo=UTC)
    snapshot = SimpleNamespace(
        timestamp=now, battery_soc=18.0, grid_export_kw=1.083, grid_import_kw=0.0
    )
    control = SimpleNamespace(
        commands_permitted=True, desired_battery_export_power_kw=0.411
    )
    agile = {
        "rolling_export_plan": {"available": True},
        "current_routing_snapshot": {"generated_at": "earlier advisory scan"},
    }
    guard = {
        "physical_soc_percent": 18.0,
        "physical_soc_lower_bound_percent": 17.935,
        "physical_bound_snapshot_at": now.isoformat(),
        "physical_bound_guard_at": now.isoformat(),
        "physical_bound_ledger_accepted": True,
        "soc_freshness_basis": "session_physical_energy_ledger_with_gap_debits",
        "physical_energy_evidence": {"status": "new_verified_soc_anchor"},
    }

    def route():
        return agile_current_export_execution_observation(
            snapshot=snapshot, control=control, agile_state=agile, physical_guard=guard
        )["routing_provenance"]

    assert route()["physical_lower_bound_soc_percent"] == 17.935
    assert route()["physical_lower_bound_ledger_accepted"] is True
    guard["physical_bound_ledger_accepted"] = False
    assert route()["physical_lower_bound_soc_percent"] == 17.935
    assert route()["physical_lower_bound_ledger_accepted"] is False
    guard["physical_bound_snapshot_at"] = "old"
    assert route()["physical_lower_bound_soc_percent"] is None


def test_summary_reuses_full_digest_and_preserves_full_cached_result():
    cache = HistoricalReplayCache(max_days=1)
    day = date(2026, 11, 23)
    today = date(2026, 11, 24)
    records = [{"energy": 1.0}]
    calls = []

    def calculate():
        calls.append(1)
        return {
            "ready": True,
            "agile_smart_export": {"ending_soc_percent": records[0]["energy"]},
            "slot_plan": [{"kwh": 1.0}],
        }

    def evaluate(summary_only=True, projection=False):
        return cache.evaluate(
            day=day,
            today=today,
            projection=projection,
            inputs=(records,),
            calculate=calculate,
            summary_only=summary_only,
        )

    first = evaluate()
    assert "slot_plan" not in first
    assert evaluate() == first
    assert len(calls) == 1
    assert cache.status["historical_summary_hits"] == 1
    assert cache.status["pickle_fingerprints"] == 2
    first["agile_smart_export"]["ending_soc_percent"] = 99.0
    assert evaluate()["agile_smart_export"]["ending_soc_percent"] == 1.0
    assert evaluate(False)["slot_plan"] == [{"kwh": 1.0}]
    records[0]["energy"] = 2.0
    assert evaluate()["agile_smart_export"]["ending_soc_percent"] == 2.0
    assert len(calls) == 2
    assert "slot_plan" in evaluate(projection=True)
    assert len(calls) == 3
