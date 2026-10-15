"""Alpha9.100 reporting-only cleanup: don't couple simulations to live authority."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_optional_replay_is_disabled_only_after_explicit_operator_choice() -> None:
    constants = (KEMS / "const.py").read_text(encoding="utf-8")
    flow = (KEMS / "config_flow.py").read_text(encoding="utf-8")
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    assert (
        'CONF_DETAILED_COMPARISONS_ENABLED = "detailed_comparisons_enabled"'
        in constants
    )
    assert "CONF_DETAILED_COMPARISONS_ENABLED: True" in constants
    assert "vol.Required(CONF_DETAILED_COMPARISONS_ENABLED): BOOLEAN_SELECTOR" in flow
    assert (
        "self.entry.options.get(CONF_DETAILED_COMPARISONS_ENABLED, True)" in coordinator
    )
    assert "scenarios = self._scenarios.baseline_only(" in coordinator
    assert "scenarios = self._scenarios.compare(" in coordinator


def test_scenario_switch_has_no_inverter_or_ev_control_authority() -> None:
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    begin = coordinator.index(
        "if self.entry.options.get(CONF_DETAILED_COMPARISONS_ENABLED"
    )
    end = coordinator.index("agile_records = await", begin)
    block = coordinator[begin:end]
    assert "self._scenarios.compare(" in block
    assert "self._scenarios.baseline_only(" in block
    for forbidden in (
        "self._control.plan(",
        "self._foxess_control.async_update(",
        "self._happy_hour_ohme.async_update(",
        "self._roi.evaluate(",
        "self._forecast_planning.plan(",
    ):
        assert forbidden not in block
    assert (
        coordinator.index("planning_simulation = self._simulation.simulate_today")
        < begin
    )
    assert (
        coordinator.index("base_simulation = self._simulation.simulate_today") < begin
    )
    assert coordinator.index("control = self._control.plan(") > end
    assert (
        coordinator.index("foxess_control = await self._foxess_control.async_update(")
        > end
    )


def test_diagnostic_trim_does_not_modify_ev_trace_recorder_or_history() -> None:
    diagnostics = (KEMS / "diagnostics.py").read_text(encoding="utf-8")
    recorder = (KEMS / "ev_charge_trace.py").read_text(encoding="utf-8")
    assert 'ev_trace["samples"] = ev_trace_samples[-64:]' in diagnostics
    assert 'ev_trace["samples_omitted"]' in diagnostics
    assert "MAX_RECORDS = 960" in recorder
    assert "RETENTION_HOURS = 72" in recorder
    assert "await self._history.async_record(snapshot)" in (
        KEMS / "coordinator.py"
    ).read_text(encoding="utf-8")


def test_actual_roi_still_uses_meter_based_no_system_ledger() -> None:
    simulation = (KEMS / "kems_core" / "simulation.py").read_text(encoding="utf-8")
    roi = (KEMS / "kems_core" / "roi.py").read_text(encoding="utf-8")
    assert "baseline_import_cost += actual_house_kwh * rate" in simulation
    assert (
        "actual_avoided_import_value = baseline_import_cost - actual_import_cost"
        in simulation
    )
    assert (
        "actual_system_value = actual_avoided_import_value + actual_export_income"
        in simulation
    )
    assert "actual_value = ledger.actual_system_value_pence / 100" in roi


def test_today_side_by_side_uses_bill_equivalent_source() -> None:
    """The comparison card must retain canonical bill totals."""
    from pathlib import Path

    root = Path(__file__).parents[1]
    source = (root / "dashboards/kems_master_dashboard.yaml").read_text()
    packaged = (root / "custom_components/kems/kems_master_dashboard.yaml").read_text()
    assert source == packaged
    home = source.split("  - title: Home", 1)[1].split("  - title: Live Data", 1)[0]
    second = source.split("title: Today — side by side", 1)[1].split(
        "- type: history-graph", 1
    )[0]
    assert "sensor.kems_energy_cost_comparison" in home
    assert "total_energy_cost_pence" in home
    assert "electricity_export_income_pence" in home
    assert "sensor.kems_simulated_kems_cost_today" not in home
    assert "sensor.kems_energy_cost_comparison" in second
    assert "total_energy_cost_pence" in second
    assert "electricity_total_cost_pence" in second
    assert "gas_total_cost_pence" in second
    assert "sensor.kems_simulated_kems_cost_today" not in second
    assert "not interchangeable with this total" in second
