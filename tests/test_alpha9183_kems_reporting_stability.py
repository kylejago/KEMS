"""Alpha9.183 KEMS-only overnight/reporting safety regressions."""

from pathlib import Path

from kems_core.roi_reward_audit import _entry

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def _source(name: str) -> str:
    return (KEMS / name).read_text(encoding="utf-8")


def test_reward_rows_have_nullable_coverage_and_event_fields():
    row = _entry("power_down", "x", "2026-11-03", None, "pending", False, False)
    assert row["coverage_percent"] is None
    assert row["modelled_agile_export_income_pence"] is None
    assert row["event_id"] is None
    assert row["supplier_status"] == "unsettled"


def test_roi_dashboard_uses_safe_mapping_lookup_for_optional_rewards():
    template = _source("kems_roi_lifetime_dashboard.yaml")
    assert "item.get('coverage_percent')" in template
    assert "item.get('modelled_agile_export_income_pence')" in template
    assert "item.coverage_percent" not in template


def test_correctable_lifetime_totals_use_total_not_total_increasing():
    source = _source("sensor.py")
    for key in ("lifetime_house_consumption", "lifetime_total_home_energy"):
        block = source.split(f'key="{key}"', 1)[1].split("value_fn=", 1)[0]
        assert "state_class=SensorStateClass.TOTAL," in block
        assert "TOTAL_INCREASING" not in block


def test_final_deadline_owner_defer_guard_is_restored_on_error():
    deadline = _source("agile_deadline_settlement_consistency.py")
    flow = _source("agile_flow_presentation.py")
    assert "self._kems_defer_flow_settlement_publish = True" in deadline
    assert "self._kems_defer_flow_settlement_publish = prior_flow" in deadline
    assert "if deferred_to_deadline:" in flow
    assert "else:\n            self._publish(self._state)" in flow
    assert "self._publish(self._state)" in deadline


def test_cheap_handover_display_does_not_change_control_authority():
    coordinator = _source("coordinator.py")
    sensor = _source("sensor.py")
    assert "display_forecast = (" in coordinator
    assert "if snapshot.cheap_period_confirmed and forecast_plan.ready" in coordinator
    assert "forecast_plan=display_forecast" in coordinator
    assert 'data.control.desired_work_mode == "Force Charge"' in sensor
    assert "scan_thread_cpu_seconds" in coordinator
