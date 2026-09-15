"""Alpha9.48 FoxESS daily physical-energy authority regression contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "alpha948_physical_daily_actual.py"
ENTRYPOINT = KEMS / "__init__.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha948_discovers_all_same_device_daily_physical_counters() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    for entity_key, name in (
        ("load_energy_today", "Load Energy Today"),
        ("grid_consumption_energy_today", "Grid Consumption Today"),
        ("feed_in_energy_today", "Feed-in Today"),
        ("battery_charge_today", "Battery Charge Today"),
        ("battery_discharge_today", "Battery Discharge Today"),
    ):
        assert entity_key in source
        assert name in source

    assert 'str(entry.platform).casefold().strip() != "foxess_modbus"' in source
    assert "entry.device_id != preferred_device" in source
    assert 'if "today" not in normalised:' in source
    assert 'entry.entity_id.split(".", 1)[0] != "sensor"' in source


def test_alpha948_persists_direct_daily_physical_sidecars() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    for sidecar in (
        "actual_house_consumption_today_kwh",
        "actual_grid_import_today_kwh",
        "actual_grid_export_today_kwh",
        "actual_battery_charge_today_kwh",
        "actual_battery_discharge_today_kwh",
    ):
        assert sidecar in source

    assert "Snapshot.to_dict = patched_to_dict" in source
    assert "Snapshot.from_dict = classmethod(patched_from_dict)" in source
    assert "_DIRECT_BY_TIMESTAMP" in source


def test_alpha948_promotes_energy_but_never_invents_tariff_timing() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    for field in (
        "actual_house_consumption_kwh",
        "actual_grid_import_kwh",
        "actual_grid_export_kwh",
        "actual_battery_charge_kwh",
        "actual_battery_discharge_kwh",
    ):
        assert field in source

    assert "replace(result, **replacements)" in source
    assert "integrated instantaneous physical power fallback" in source
    assert "aggregate daily energy counters do not invent tariff timing" in source
    assert "physical_balance_residual_kwh" in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "commands_permitted = True" not in source
    assert "safe_to_write_hardware = True" not in source


def test_alpha948_installs_before_first_refresh_and_release_metadata_is_current() -> (
    None
):
    source = SOURCE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.48"
    assert "Alpha9.48" in reason
    assert "Load Energy Today" in reason
    assert "Grid Consumption Today" in reason
    assert "Feed-in Today" in reason
    assert entrypoint.index(
        "install_alpha948_physical_daily_actual()"
    ) < entrypoint.index("await coordinator.async_config_entry_first_refresh()")
    assert entrypoint.index("install_alpha946_solar_actual()") < entrypoint.index(
        "install_alpha948_physical_daily_actual()"
    )
    assert '"hardware_writes": "blocked"' in source
