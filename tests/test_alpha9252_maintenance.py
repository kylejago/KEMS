"""Read-only maintenance regressions for Alpha9.253."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from kems_core.agile_historical_replay_cache import HistoricalReplayCache
from kems_core.diagnostic_evidence import agile_current_export_execution_observation


def test_checkpoint_isolation_retains_digest_and_copy_metrics():
    cache = HistoricalReplayCache()
    day = date(2026, 11, 23)
    today = date(2026, 11, 24)
    inputs = ([{"kw": 1.0}],)
    result = {"slot_plan": [{"kw": 2.0}]}
    cache.evaluate(
        day=day,
        today=today,
        projection=False,
        inputs=inputs,
        calculate=lambda: result,
    )
    before = cache.status
    saved = cache.export_state()
    saved["entries"][0]["result"]["slot_plan"][0]["kw"] = 99.0
    assert cache.status == before
    assert cache.export_state()["entries"][0]["result"] == result
    assert (
        cache.get_cached(day=day, today=today, projection=False, inputs=inputs)
        == result
    )
    inputs[0][0]["kw"] = 3.0
    assert (
        cache.get_cached(day=day, today=today, projection=False, inputs=inputs) is None
    )


def test_routing_authorities_remain_separate_and_fail_closed():
    now = datetime(2026, 11, 24, 21, 15, tzinfo=UTC)
    snapshot = SimpleNamespace(
        timestamp=now, battery_soc=20.0, grid_export_kw=0.656, grid_import_kw=0.0
    )
    control = SimpleNamespace(
        desired_battery_export_power_kw=0.469,
        desired_total_discharge_power_kw=1.323,
        commands_permitted=True,
    )
    state = {
        "rolling_export_plan": {
            "available": True,
            "current_battery_export_target_kw": 0.899,
            "simulated_soc_percent": 22.03,
            "forecast_path_reconciled_ending_soc_percent": 14.735,
            "forecast_path_theoretical_ending_soc_percent": 11.971,
        },
        "current_routing_snapshot": {
            "generated_at": now.isoformat(),
            "version": "0.7.0-alpha7.30",
            "battery_export_kw": 0.899,
            "grid_export_kw": 0.899,
        },
    }
    guard = {
        "requested_export_kw": 0.899,
        "permitted_export_kw": 0.469,
        "physical_soc_lower_bound_percent": 19.362,
        "physical_soc_percent": 20.0,
        "physical_bound_snapshot_at": now.isoformat(),
        "physical_bound_guard_at": now.isoformat(),
        "physical_bound_ledger_accepted": True,
        "status": "capped",
        "physical_energy_evidence": {
            "status": "verified_power_continuity_with_margin",
            "observed_at": now.isoformat(),
        },
    }
    result = agile_current_export_execution_observation(
        snapshot=snapshot, control=control, agile_state=state, physical_guard=guard
    )
    route = result["routing_provenance"]
    assert route["proposal_battery_export_kw"] == 0.899
    assert route["guard_permitted_battery_export_kw"] == 0.469
    assert route["authorised_battery_export_kw"] == 0.469
    assert route["measured_grid_export_kw"] == 0.656
    assert route["physical_lower_bound_soc_percent"] == 19.362
    assert route["twin_minus_physical_soc_percentage_points"] == 2.03
    assert route["arrival_guaranteed"] is False
    assert result["physical_dispatch_verified"] is False
    assert state["current_routing_snapshot"]["battery_export_kw"] == 0.899

    control.commands_permitted = False
    guard["physical_bound_snapshot_at"] = "old"
    route = agile_current_export_execution_observation(
        snapshot=snapshot, control=control, agile_state=state, physical_guard=guard
    )["routing_provenance"]
    assert route["authorised_battery_export_kw"] is None
    assert route["physical_lower_bound_soc_percent"] is None
