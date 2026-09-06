from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "custom_components/kems/kems_core/simulation.py"
TEST = ROOT / "tests/test_alpha94_simulation_commissioning_separation.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    SIM,
    '''            starting_soc = (\n                snapshot.battery_soc\n                if snapshot.battery_soc is not None\n                else config.battery_initial_percent\n            )\n''',
    '''            fresh_battery_soc = _fresh_snapshot_value(snapshot, "battery_soc")\n            starting_soc = (\n                fresh_battery_soc\n                if fresh_battery_soc is not None\n                else config.battery_initial_percent\n            )\n''',
)
replace_once(
    SIM,
    '''        if len(previous_day_records) < 2:\n            if latest_previous.battery_soc is None:\n                return initial\n            observed = (\n                capacity\n                * min(\n                    max(latest_previous.battery_soc, 0.0),\n                    100.0,\n                )\n                / 100\n            )\n            return min(max(observed, reserve_kwh), capacity)\n''',
    '''        if len(previous_day_records) < 2:\n            previous_soc = _fresh_snapshot_value(latest_previous, "battery_soc")\n            if previous_soc is None:\n                return initial\n            observed = (\n                capacity\n                * min(\n                    max(previous_soc, 0.0),\n                    100.0,\n                )\n                / 100\n            )\n            return min(max(observed, reserve_kwh), capacity)\n''',
)

text = TEST.read_text(encoding="utf-8")
marker = "def test_foxess_binding_separates_commands_from_sensor_readback_without_writes()"
if marker not in text:
    raise SystemExit("Alpha9.4 binding test marker not found")
addition = '''\n\ndef test_single_sample_does_not_adopt_stale_physical_soc() -> None:\n    timestamp = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)\n    snapshot = Snapshot(\n        timestamp=timestamp,\n        current_import_rate=28.3,\n        house_load_kw=1.2,\n        grid_import_kw=1.2,\n        battery_soc=99.0,\n        solar_power_kw=None,\n        stale_fields=("battery_soc", "solar_power_kw"),\n    )\n    result = SimulationEngine().simulate_today(\n        [snapshot],\n        timestamp + timedelta(minutes=1),\n        SimulationConfig(\n            battery_initial_percent=50.0,\n            proposal_solar_enabled=True,\n        ),\n        current_snapshot=snapshot,\n    )\n\n    assert result.simulated_battery_soc == 50.0\n    assert result.proposal_solar_active is True\n\n\ndef test_midnight_carry_does_not_adopt_stale_previous_physical_soc() -> None:\n    previous = Snapshot(\n        timestamp=datetime(2026, 9, 5, 23, 45, tzinfo=UTC),\n        current_import_rate=28.3,\n        house_load_kw=1.2,\n        grid_import_kw=1.2,\n        battery_soc=99.0,\n        stale_fields=("battery_soc",),\n    )\n    current_start = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)\n    current = [\n        Snapshot(\n            timestamp=current_start + timedelta(minutes=15 * index),\n            current_import_rate=28.3,\n            house_load_kw=0.0,\n            grid_import_kw=0.0,\n            battery_soc=None,\n            stale_fields=("battery_soc",),\n        )\n        for index in range(2)\n    ]\n    result = SimulationEngine().simulate_today(\n        [previous, *current],\n        current[-1].timestamp + timedelta(minutes=1),\n        SimulationConfig(battery_initial_percent=50.0),\n        current_snapshot=current[-1],\n    )\n\n    assert result.ready is True\n    assert result.simulated_battery_soc == 50.0\n'''
if "test_single_sample_does_not_adopt_stale_physical_soc" in text:
    raise SystemExit("Alpha9.4 edge tests already present")
TEST.write_text(text.replace("\n\n" + marker, addition + "\n\n" + marker, 1), encoding="utf-8")

Path(__file__).unlink()
