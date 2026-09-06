"""Alpha9.4 simulation/physical-commissioning separation contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kems_core import (
    ScenarioComparisonEngine,
    SimulationConfig,
    SimulationEngine,
    Snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "custom_components/kems/foxess_command_shadow.py"


def _offline_foxess_records() -> list[Snapshot]:
    start = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    stale_physical = (
        "battery_power_kw",
        "battery_soc",
        "grid_export_kw",
        "solar_power_kw",
    )
    return [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            current_import_rate=28.3,
            next_import_rate=28.3,
            off_peak=False,
            house_load_kw=1.2,
            grid_import_kw=1.2,
            battery_soc=None,
            battery_power_kw=None,
            solar_power_kw=None,
            grid_export_kw=None,
            stale_fields=stale_physical,
        )
        for index in range(4)
    ]


def test_uncommissioned_offline_foxess_does_not_block_virtual_simulation() -> None:
    records = _offline_foxess_records()
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_initial_percent=50.0,
            proposal_solar_enabled=True,
        ),
        current_snapshot=records[-1],
    )

    assert result.ready is True
    assert result.data_coverage == 100.0
    assert result.proposal_solar_active is True
    assert result.simulated_grid_import_kwh is not None
    assert result.simulated_battery_soc is not None
    assert result.actual_solar_generation_kwh == 0.0
    assert result.actual_battery_charge_kwh == 0.0
    assert result.actual_battery_discharge_kwh == 0.0
    assert result.actual_grid_export_kwh == 0.0


def test_current_day_scenarios_survive_uncommissioned_offline_foxess() -> None:
    records = _offline_foxess_records()
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_initial_percent=50.0,
            proposal_solar_enabled=True,
        ),
        current_snapshot=records[-1],
    )
    today = result.periods["today"]
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


def test_stale_required_house_and_grid_evidence_still_fails_closed() -> None:
    records = _offline_foxess_records()
    records = [
        Snapshot.from_dict(
            {
                **record.to_dict(),
                "stale_fields": [
                    *record.stale_fields,
                    "house_load_kw",
                    "grid_import_kw",
                ],
            }
        )
        for record in records
    ]
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(proposal_solar_enabled=True),
        current_snapshot=records[-1],
    )

    assert result.ready is False
    assert result.data_coverage == 0.0


def test_single_sample_does_not_adopt_stale_physical_soc() -> None:
    timestamp = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=timestamp,
        current_import_rate=28.3,
        house_load_kw=1.2,
        grid_import_kw=1.2,
        battery_soc=99.0,
        solar_power_kw=None,
        stale_fields=("battery_soc", "solar_power_kw"),
    )
    result = SimulationEngine().simulate_today(
        [snapshot],
        timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_initial_percent=50.0,
            proposal_solar_enabled=True,
        ),
        current_snapshot=snapshot,
    )

    assert result.simulated_battery_soc == 50.0
    assert result.proposal_solar_active is True


def test_midnight_carry_does_not_adopt_stale_previous_physical_soc() -> None:
    previous = Snapshot(
        timestamp=datetime(2026, 9, 5, 23, 45, tzinfo=UTC),
        current_import_rate=28.3,
        house_load_kw=1.2,
        grid_import_kw=1.2,
        battery_soc=99.0,
        stale_fields=("battery_soc",),
    )
    current_start = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
    current = [
        Snapshot(
            timestamp=current_start + timedelta(minutes=15 * index),
            current_import_rate=28.3,
            house_load_kw=0.0,
            grid_import_kw=0.0,
            battery_soc=None,
            stale_fields=("battery_soc",),
        )
        for index in range(4)
    ]
    result = SimulationEngine().simulate_today(
        [previous, *current],
        current[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(battery_initial_percent=50.0),
        current_snapshot=current[-1],
    )

    assert result.ready is True
    assert result.data_coverage == 100.0
    assert result.simulated_battery_soc == 50.0


def test_foxess_binding_separates_commands_from_sensor_readback_without_writes() -> (
    None
):
    source = ADAPTER.read_text(encoding="utf-8")

    assert '"work_mode": "select"' in source
    for key in (
        "force_charge_power",
        "force_discharge_power",
        "min_soc_on_grid",
        "export_power_limit",
    ):
        assert f'"{key}": "number"' in source
    assert "_entry_readback_key" in source
    assert 'domain == "sensor"' in source
    assert '"readback_entity_id"' in source
    assert '"observation_source"' in source
    assert '"sensor_readback"' in source

    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
        "ModbusClient",
    ):
        assert forbidden not in source
