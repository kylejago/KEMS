"""Regression coverage for Alpha8.36 pre-cheap home-load bridging."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import types
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _load_modules():
    """Load Agile runtime pieces with the same tiny HA stubs as core tests."""
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    sys.modules.setdefault("aiohttp", aiohttp)

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __class_getitem__(cls, item):
            return cls

    storage.Store = Store
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault("homeassistant.helpers.storage", storage)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(INTEGRATION)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.kems", package)

    agile_name = "custom_components.kems.agile_smart_export"
    spec = importlib.util.spec_from_file_location(
        agile_name,
        INTEGRATION / "agile_smart_export.py",
    )
    assert spec is not None and spec.loader is not None
    agile = importlib.util.module_from_spec(spec)
    sys.modules[agile_name] = agile
    spec.loader.exec_module(agile)

    runtime_base = importlib.import_module(
        "custom_components.kems.agile_smart_export_runtime_base"
    )
    bridge = importlib.import_module(
        "custom_components.kems.agile_precheap_home_bridge"
    )
    deadline = importlib.import_module("custom_components.kems.agile_deadline_dispatch")
    tariff_module = importlib.import_module("custom_components.kems.tariff")
    bridge.install_precheap_home_bridge()
    return agile, runtime_base, bridge, deadline, tariff_module


def _records(agile):
    timestamps = [
        datetime(2026, 8, 28, 22, 0, tzinfo=LONDON),
        datetime(2026, 8, 28, 22, 30, tzinfo=LONDON),
        datetime(2026, 8, 28, 23, 0, tzinfo=LONDON),
        datetime(2026, 8, 28, 23, 30, tzinfo=LONDON),
        datetime(2026, 8, 29, 0, 0, tzinfo=LONDON),
    ]
    return [
        agile.Snapshot(
            timestamp=stamp,
            current_import_rate=(
                3.49 if stamp.hour >= 23 and stamp.minute >= 30 else 28.3
            ),
            next_import_rate=3.49,
            electricity_standing_charge=53.7,
            off_peak=(stamp.hour >= 23 and stamp.minute >= 30) or stamp.hour == 0,
            intelligent_slot=False,
            house_load_kw=1.392,
            solar_power_kw=0.0,
        )
        for stamp in timestamps
    ]


def _config(agile):
    return agile.SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        battery_initial_percent=14.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        export_rate_pence=12.0,
        export_tariff_status="active",
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        battery_export_enabled=True,
    )


def _tariff(tariff_module):
    return tariff_module.TariffSettings(
        mode="manual",
        day_rate_pence=28.3,
        offpeak_rate_pence=3.49,
        standing_charge_pence=53.7,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=False,
    )


def test_bridge_floor_declines_to_ten_percent_at_cheap_start() -> None:
    agile, _, _, _, _ = _load_modules()
    manager = object.__new__(agile.AgileSmartExportManager)
    manager._simulation = agile.SimulationEngine()
    records = _records(agile)
    config = _config(agile)
    capacity = config.battery_capacity_kwh
    reserve = capacity * 0.10

    floor_2200 = manager._floor(records, 0, records[0], config, reserve, capacity)
    floor_2230 = manager._floor(records, 1, records[1], config, reserve, capacity)
    floor_2300 = manager._floor(records, 2, records[2], config, reserve, capacity)

    assert round(100 * floor_2200 / capacity, 1) > 12.0
    assert round(100 * floor_2230 / capacity, 1) > 11.0
    assert round(100 * floor_2300 / capacity, 1) == 10.0
    assert floor_2200 > floor_2230 > floor_2300


def test_partial_tomorrow_prices_do_not_force_2230_grid_import() -> None:
    agile, _, _, deadline, tariff_module = _load_modules()
    manager = object.__new__(agile.AgileSmartExportManager)
    manager._simulation = agile.SimulationEngine()
    records = _records(agile)
    config = _config(agile)
    rates = [
        agile.AgileRate(
            "AGILE-OUTGOING-TEST",
            "E-1R-AGILE-OUTGOING-TEST-L",
            value,
            start,
            start + timedelta(minutes=30),
        )
        for start, value in (
            (records[0].timestamp, 20.0),
            (records[1].timestamp, 12.7),
        )
    ]

    _, plan = deadline.agile_day_with_deadline(
        manager,
        records,
        rates,
        config,
        _tariff(tariff_module),
        14.0,
    )
    row = next(
        item
        for item in plan
        if datetime.fromisoformat(item["valid_from"])
        .astimezone(LONDON)
        .strftime("%H:%M")
        == "22:30"
    )

    assert row["grid_import_kwh"] == 0.0
    assert row["battery_to_home_kwh"] > 0.69
    assert row["ending_soc_percent"] > 10.0


def test_noncheap_grid_import_is_not_reported_as_grid_to_battery() -> None:
    agile, runtime_base, _, _, _ = _load_modules()
    records = _records(agile)[1:3]
    config = _config(agile)
    slots = [
        {
            "valid_from": records[0].timestamp.isoformat(),
            "valid_to": records[1].timestamp.isoformat(),
            "grid_import_kwh": 0.696,
        }
    ]

    runtime_base._enrich_slot_routing(
        slots,
        records,
        config,
        agile.SimulationEngine(),
    )
    assert slots[0]["grid_to_battery_kwh"] == 0.0


def test_precheap_bridge_runs_before_final_deadline_dominance() -> None:
    compat = (INTEGRATION / "agile_alpha7_compat.py").read_text(encoding="utf-8")
    bridge = (INTEGRATION / "agile_precheap_home_bridge.py").read_text(encoding="utf-8")

    assert compat.rfind("install_precheap_home_bridge") > compat.rfind(
        "install_total_discharge_ledger"
    )
    assert compat.rfind("install_deadline_dominance") > compat.rfind(
        "install_precheap_home_bridge"
    )
    assert "forecast net house demand" in bridge
    assert "grid_to_battery_kwh" in bridge
    assert '"hardware_writes"' not in bridge
    assert ".services.async_call(" not in bridge


def test_alpha836_version_and_release_scope() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    version = str(manifest["version"])
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert (
        str(version).startswith("0.9.0-alpha9") or int(version.rsplit(".", 1)[-1]) >= 36
    )
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert str(bundle["components"]["property_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
