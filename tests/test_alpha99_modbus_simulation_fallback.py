"""Alpha9.9 Modbus/source-authority simulation fallback contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kems_core import (
    ControlConfig,
    ControlEngine,
    ScenarioComparisonEngine,
    SimulationConfig,
    SimulationEngine,
    Snapshot,
)
from kems_core.simulation_fallback import (
    apply_simulation_demand_fallback,
    resolve_octopus_current_demand_entity,
    simulation_fallback_age_key,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_octopus_current_demand_survives_foxess_source_promotion() -> None:
    """The tariff mapping can recover the exact sibling demand sensor."""
    rate = "sensor.octopus_energy_electricity_1234567890123_" "20l1234567_current_rate"
    demand = (
        "sensor.octopus_energy_electricity_1234567890123_" "20l1234567_current_demand"
    )

    resolved = resolve_octopus_current_demand_entity(
        house_load_entity="sensor.kh7_load_power",
        grid_import_entity="sensor.kh7_grid_consumption",
        current_import_rate_entity=rate,
        state_exists=lambda entity_id: entity_id == demand,
    )

    assert resolved == demand


def test_fallback_retains_physical_staleness_and_marks_simulation_provenance() -> None:
    """Octopus demand must never masquerade as fresh commissioned FoxESS data."""
    evidence = apply_simulation_demand_fallback(
        physical_house_load_kw=None,
        physical_grid_import_kw=None,
        physical_source_age_seconds={"battery_soc": 600.0},
        physical_stale_fields=("battery_soc",),
        fallback_demand_kw=1.234,
        fallback_age_seconds=15.0,
    )

    assert evidence.house_load_kw == 1.234
    assert evidence.grid_import_kw == 1.234
    assert evidence.fallback_fields == ("house_load_kw", "grid_import_kw")
    assert "house_load_kw" in evidence.stale_fields
    assert "grid_import_kw" in evidence.stale_fields
    assert "battery_soc" in evidence.stale_fields
    assert (
        evidence.source_age_seconds[simulation_fallback_age_key("house_load_kw")]
        == 15.0
    )
    assert (
        evidence.source_age_seconds[simulation_fallback_age_key("grid_import_kw")]
        == 15.0
    )


def _fallback_records() -> list[Snapshot]:
    start = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    records: list[Snapshot] = []
    for index in range(5):
        evidence = apply_simulation_demand_fallback(
            physical_house_load_kw=None,
            physical_grid_import_kw=None,
            physical_source_age_seconds={
                "battery_soc": 600.0,
                "battery_power_kw": 600.0,
                "solar_power_kw": 600.0,
                "grid_export_kw": 600.0,
            },
            physical_stale_fields=(
                "battery_power_kw",
                "battery_soc",
                "grid_export_kw",
                "solar_power_kw",
            ),
            fallback_demand_kw=1.2,
            fallback_age_seconds=10.0,
        )
        records.append(
            Snapshot(
                timestamp=start + timedelta(minutes=15 * index),
                current_import_rate=28.3,
                next_import_rate=28.3,
                off_peak=False,
                house_load_kw=evidence.house_load_kw,
                grid_import_kw=evidence.grid_import_kw,
                battery_soc=None,
                battery_power_kw=None,
                solar_power_kw=None,
                grid_export_kw=None,
                source_age_seconds=evidence.source_age_seconds,
                stale_fields=evidence.stale_fields,
                source_data_age_seconds=600.0,
            )
        )
    return records


def test_virtual_simulation_and_compare_use_explicit_octopus_demand_fallback() -> None:
    """Registered-but-offline Modbus must not blank KEMS replay or Compare."""
    records = _fallback_records()
    now = records[-1].timestamp + timedelta(minutes=1)
    config = SimulationConfig(
        battery_initial_percent=50.0,
        proposal_solar_enabled=True,
    )

    simulation = SimulationEngine().simulate_today(
        records,
        now,
        config,
        current_snapshot=records[-1],
    )
    comparison = ScenarioComparisonEngine().compare(
        records,
        now,
        config,
        current_snapshot=records[-1],
    )

    assert simulation.ready is True
    assert simulation.data_coverage == 100.0
    assert simulation.actual_house_consumption_kwh is not None
    assert simulation.simulated_grid_import_kwh is not None

    today = comparison.periods["today"]
    summaries = {item.key: item for item in today.scenarios}
    for key in (
        "no_system",
        "solar_only",
        "solar_battery",
        "kems_no_export",
        "kems_full",
        "kems_forecast",
        "full_island",
    ):
        assert summaries[key].ready is True, key
        assert summaries[key].data_coverage == 100.0, key


def test_unmarked_stale_house_and_grid_still_fail_simulation_closed() -> None:
    """Alpha9.9 does not weaken the existing required-demand freshness gate."""
    records = _fallback_records()
    unmarked = [
        Snapshot.from_dict(
            {
                **record.to_dict(),
                "source_age_seconds": {
                    key: value
                    for key, value in record.source_age_seconds.items()
                    if not key.startswith("simulation_fallback_")
                },
            }
        )
        for record in records
    ]

    result = SimulationEngine().simulate_today(
        unmarked,
        unmarked[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(proposal_solar_enabled=True),
        current_snapshot=unmarked[-1],
    )

    assert result.ready is False
    assert result.data_coverage == 0.0


def test_hardware_control_remains_fail_closed_while_fallback_drives_simulation() -> (
    None
):
    """Simulation health must not turn Octopus demand into hardware authority."""
    records = _fallback_records()
    now = records[-1].timestamp + timedelta(minutes=1)
    simulation = SimulationEngine().simulate_today(
        records,
        now,
        SimulationConfig(battery_initial_percent=50.0),
        current_snapshot=records[-1],
    )
    control = ControlEngine().plan(
        records[-1],
        simulation,
        now,
        ControlConfig(),
    )

    assert simulation.ready is True
    assert control.data_fresh is False
    assert control.plan_safe is False
    assert control.operating_reason == "stale_data_failsafe"
    assert control.commands_permitted is False
    assert control.real_backend_available is False


def test_runtime_wiring_uses_fallback_without_foxess_writes() -> None:
    """Collector/provider wiring is read-only and keeps the provenance contract."""
    provider = (KEMS / "providers/octopus.py").read_text(encoding="utf-8")
    collector = (KEMS / "collector.py").read_text(encoding="utf-8")
    fallback = (KEMS / "kems_core/simulation_fallback.py").read_text(encoding="utf-8")
    sources = "\n".join((provider, collector, fallback))

    assert "resolve_octopus_current_demand_entity(" in provider
    assert "current_demand_age_seconds" in provider
    assert "apply_simulation_demand_fallback(" in collector
    assert "physical_stale_fields=foxess.stale_fields" in collector
    assert "simulation_fallback_age_key" in fallback

    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
    ):
        assert forbidden not in sources
