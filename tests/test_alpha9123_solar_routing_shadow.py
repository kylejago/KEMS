"""Alpha9.123 economic solar routing is read-only and respects live priority."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from solar_routing_shadow import (
    evaluate_solar_routing_shadow,
    publish_solar_routing_shadow,
)

NOW = datetime(2026, 10, 22, 12, 10, tzinfo=UTC)


def _slot(at: datetime, rate: float, *, spare: float = 3.0, used: float = 0.0):
    return {
        "valid_from": at.isoformat(),
        "valid_to": (at + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
        "physical_export_capacity_kwh": spare,
        "planned_battery_export_kwh": used,
        "label": at.strftime("%H:%M"),
    }


def _inputs(*, current_rate: float = 12.0, future_rate: float = 30.0):
    plan = {
        "available": True,
        "current_battery_export_target_kw": 0.0,
        "planning_soc_percent": 75.0,
        "protected_house_energy_kwh": 8.0,
        "selected_slots": [_slot(NOW + timedelta(hours=5), future_rate)],
    }
    rates = {
        "live_ready": True,
        "ready": False,  # daily settlement publication need not be complete
        "battery_wear_assumption_pence_per_discharged_kwh": 2.0,
        "today_slots": [_slot(NOW, current_rate)],
        "rolling_export_plan": plan,
        "current_routing_snapshot": {"solar_export_kw": 3.3},
    }
    snapshot = SimpleNamespace(
        solar_power_kw=3.5,
        house_load_kw=0.2,
        battery_power_kw=-3.3,
        grid_export_kw=0.0,
        grid_import_kw=0.0,
        battery_soc=75.0,
        cheap_period_confirmed=False,
        saving_session_active=False,
        stale_fields=(),
    )
    forecast = SimpleNamespace(ready=True, confidence_percent=72.0)
    future = SimpleNamespace(
        ready=True,
        predicted_day_rate_import_kwh=0.0,
        battery_retention_required=False,
    )
    config = SimpleNamespace(
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        export_limit_kw=7.0,
        inverter_limit_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
    )
    return {
        "now": NOW,
        "agile_state": rates,
        "snapshot": snapshot,
        "forecast": forecast,
        "forecast_plan": future,
        "config": config,
        "paid_agile_selected": True,
    }


def test_store_when_future_marginal_export_benefit_exceeds_now() -> None:
    args = _inputs()
    original = deepcopy(args["agile_state"])
    result = evaluate_solar_routing_shadow(**args)
    assert result["status"] == "keep_self_use"
    assert result["stored_value_pence_per_input_kwh"] > 12.0
    assert result["hardware_writes"] == "forbidden"
    assert args["agile_state"] == original


def test_feed_in_candidate_only_when_selling_now_is_worth_more() -> None:
    result = evaluate_solar_routing_shadow(
        **_inputs(current_rate=25.0, future_rate=15.0)
    )
    assert result["status"] == "feed_in_first_candidate"
    assert result["expected_advantage_pence"] > 0
    assert result["marginal_solar_kwh"] > 0
    assert result["reporting_only"] is True


def test_saturated_future_valuable_slot_must_not_count_twice() -> None:
    args = _inputs(current_rate=10.0, future_rate=40.0)
    args["agile_state"]["rolling_export_plan"]["selected_slots"][0].update(
        physical_export_capacity_kwh=3.0, planned_battery_export_kwh=3.0
    )
    result = evaluate_solar_routing_shadow(**args)
    assert result["status"] == "keep_self_use"
    assert "no verified" not in result["reason"].lower() or result["reporting_only"]


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("cheap_period_confirmed", True, "higher_priority"),
        ("saving_session_active", True, "higher_priority"),
        ("solar_power_kw", 0.1, "no_surplus"),
    ],
)
def test_existing_physical_priorities_override_economic_candidate(
    field: str, value: object, expected: str
) -> None:
    args = _inputs(current_rate=25.0, future_rate=12.0)
    setattr(args["snapshot"], field, value)
    assert evaluate_solar_routing_shadow(**args)["status"] == expected


def test_existing_battery_export_plan_takes_priority() -> None:
    args = _inputs(current_rate=25.0, future_rate=12.0)
    args["agile_state"]["rolling_export_plan"]["current_battery_export_target_kw"] = 2.0
    assert evaluate_solar_routing_shadow(**args)["status"] == "higher_priority"


@pytest.mark.parametrize("confidence", [None, 60.0])
def test_unconfirmed_forecast_never_proposes_feed_in(confidence) -> None:
    args = _inputs(current_rate=25.0, future_rate=12.0)
    args["forecast"].confidence_percent = confidence
    assert evaluate_solar_routing_shadow(**args)["status"] == "insufficient_evidence"


def test_battery_needed_for_expensive_import_stays_self_use() -> None:
    args = _inputs(current_rate=40.0, future_rate=10.0)
    args["forecast_plan"].predicted_day_rate_import_kwh = 1.0
    result = evaluate_solar_routing_shadow(**args)
    assert result["status"] == "keep_self_use"


def test_battery_full_can_propose_feed_in_without_storage_capacity() -> None:
    args = _inputs()
    args["snapshot"].battery_soc = 100.0
    result = evaluate_solar_routing_shadow(**args)
    assert result["status"] == "feed_in_first_candidate"
    assert result["hardware_writes"] == "forbidden"


def test_missing_live_rates_and_missing_physical_readings_are_not_authority() -> None:
    args = _inputs(current_rate=25.0, future_rate=12.0)
    args["agile_state"]["live_ready"] = False
    assert evaluate_solar_routing_shadow(**args)["status"] == "insufficient_evidence"
    args["agile_state"]["live_ready"] = True
    args["snapshot"].stale_fields = ("solar_power_kw",)
    assert evaluate_solar_routing_shadow(**args)["status"] == "insufficient_evidence"


def test_observed_flow_parity_reports_disagreement_only_when_not_discharging() -> None:
    args = _inputs()
    value = evaluate_solar_routing_shadow(**args)
    assert value["digital_twin_vs_grid_export_gap_kw"] == 3.3
    args["snapshot"].battery_power_kw = 2.0
    value = evaluate_solar_routing_shadow(**args)
    assert value["digital_twin_vs_grid_export_gap_kw"] is None


def test_publication_writes_only_separate_shadow_sensor() -> None:
    class Manager:
        def __init__(self) -> None:
            self._state = {"rolling_export_plan": {"protected": True}}
            self.published: list[tuple[str, str, dict]] = []

        def _set(self, entity_id: str, value: str, attrs: dict) -> None:
            self.published.append((entity_id, value, attrs))

    mgr = Manager()
    value = evaluate_solar_routing_shadow(**_inputs())
    publish_solar_routing_shadow(mgr, value)
    assert mgr._state["rolling_export_plan"] == {"protected": True}
    assert mgr._state["solar_routing_shadow"]["reporting_only"] is True
    assert len(mgr.published) == 1
    assert mgr.published[0][0] == "sensor.kems_solar_routing_shadow"
    assert mgr.published[0][2]["hardware_writes"] == "forbidden"
