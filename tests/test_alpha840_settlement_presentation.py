"""Alpha8.40 settled current-day control and presentation regressions."""

from pathlib import Path


def test_alpha840_live_snapshot_accounting_math() -> None:
    """Lock the exact Alpha8.39 evidence behind the presentation correction."""
    import_cost_pence = 159.13
    export_income_pence = 127.56
    actual_cost_pence = 373.74
    solar_to_battery_kwh = 4.307
    grid_to_battery_kwh = 36.444
    replay_soc_percent = 80.8
    settled_battery_export_kwh = 8.338
    battery_capacity_kwh = 56.42
    discharge_efficiency = 0.95

    simulated_cost_pence = round(import_cost_pence - export_income_pence, 2)
    saving_pence = round(actual_cost_pence - simulated_cost_pence, 2)
    charged_kwh = round(solar_to_battery_kwh + grid_to_battery_kwh, 3)
    soc_delta_percent = (
        settled_battery_export_kwh / discharge_efficiency / battery_capacity_kwh * 100.0
    )
    corrected_soc_percent = round(replay_soc_percent - soc_delta_percent, 3)

    assert simulated_cost_pence == 31.57
    assert saving_pence == 342.17
    assert charged_kwh == 40.751
    assert corrected_soc_percent == 65.244


def test_alpha840_presentation_module_maps_headlines_to_settled_agile() -> None:
    """Headline simulation fields must come from the settled Agile authority."""
    source = Path(
        "custom_components/kems/agile_current_day_presentation.py"
    ).read_text()

    assert 'state.get("current_day_settlement_reconciliation")' in source
    assert 'reconciliation.get("all_accounting_checks_passed")' in source
    assert 'today.get("agile_smart_export")' in source
    assert "simulated_cost = round(import_cost - export_income - bonus, 2)" in source
    assert '"simulated_grid_export_kwh"' in source
    assert '"simulated_battery_to_home_kwh"' in source
    assert '"simulated_battery_export_kwh"' in source
    assert '"simulated_battery_soc"' in source
    assert '"simulated_system_value_pence"' in source
    assert '"effective_export_rate_pence"' in source
    assert "return replace(simulation, **replacements)" in source


def test_alpha840_unreconciled_state_preserves_generic_fallback() -> None:
    """No authoritative Agile data must still preserve the generic simulation."""
    source = Path(
        "custom_components/kems/agile_current_day_presentation.py"
    ).read_text()

    assert "agile = _today_agile(state)" in source
    assert "routing_replacements = _current_routing_replacements(state)" in source
    assert "if agile is None:" in source
    assert "else simulation" in source


def test_alpha840_coordinator_settles_before_control_and_rebuilds_after_shadow() -> (
    None
):
    """Control/shadow must see settled SOC and presentation must include new closes."""
    source = Path("custom_components/kems/coordinator.py").read_text()
    first_reconcile = source.index(
        "self._agile_smart_export.reconcile_current_day_settlements"
    )
    first_presentation = source.index(
        "simulation = reconciled_current_day_simulation(",
        first_reconcile,
    )
    alignment = source.index("aligned_agile_control_views(simulation, agile_state)")
    shadow_update = source.index("await self._shadow_validation.async_update")
    second_reconcile = source.index(
        "self._agile_smart_export.reconcile_current_day_settlements",
        first_reconcile + 1,
    )
    final_presentation = source.index(
        "simulation = reconciled_current_day_simulation(",
        second_reconcile,
    )
    whole_home = source.index("whole_home = self._whole_home.summarise")

    assert first_reconcile < first_presentation < alignment < shadow_update
    assert shadow_update < second_reconcile < final_presentation < whole_home


def test_alpha840_managed_dashboard_headlines_use_reconciled_sensor_surfaces() -> None:
    """Existing dashboard bindings inherit the reconciled backend authority."""
    master = Path("custom_components/kems/kems_master_dashboard.yaml").read_text()
    whole_home = Path("dashboards/kems_whole_home_analytics.yaml").read_text()
    sensor_source = Path("custom_components/kems/sensor.py").read_text()

    assert "sensor.kems_simulated_kems_cost_today" in master
    assert "{% set kems_e = states('sensor.kems_simulated_kems_cost_today')" in master
    assert "{% set saving = live_e - kems_e %}" in master
    assert "sensor.kems_whole_home_simulated_cost_today" in whole_home
    assert 'key="simulated_saving_today"' in sensor_source
    assert "value_fn=lambda data: data.simulation.saving_pence" in sensor_source
    assert (
        "value_fn=lambda data: data.whole_home.simulated_total_cost_pence"
        in sensor_source
    )
    assert (
        "value_fn=lambda data: data.whole_home.simulated_saving_pence" in sensor_source
    )


def test_alpha840_no_hardware_write_or_version_named_patch_debt() -> None:
    """Alpha8.40 stays reporting/control-alignment only and adds no patch module."""
    module = Path(
        "custom_components/kems/agile_current_day_presentation.py"
    ).read_text()
    coordinator = Path("custom_components/kems/coordinator.py").read_text()

    assert "service.async_call" not in module
    assert "service.async_call" not in coordinator
    assert "hardware_writes" not in module
    assert not Path("custom_components/kems/agile_alpha840.py").exists()
