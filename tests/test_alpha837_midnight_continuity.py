"""Regression coverage for Alpha8.37 midnight replay continuity."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import types
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _load_modules():
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
    handoff = importlib.import_module(
        "custom_components.kems.agile_tomorrow_soc_handoff"
    )
    tariff_module = importlib.import_module("custom_components.kems.tariff")
    charge_truth = importlib.import_module(
        "custom_components.kems.agile_shadow_charge_truth"
    )
    return agile, runtime_base, handoff, tariff_module, charge_truth


def _snapshots(agile):
    timestamps = [
        datetime(2026, 8, 27, 23, 0, tzinfo=LONDON),
        datetime(2026, 8, 27, 23, 30, tzinfo=LONDON),
        datetime(2026, 8, 28, 0, 0, tzinfo=LONDON),
        datetime(2026, 8, 28, 0, 30, tzinfo=LONDON),
    ]
    return [
        agile.Snapshot(
            timestamp=stamp,
            current_import_rate=(
                3.49 if stamp.time() >= time(23, 30) or stamp.hour == 0 else 28.3
            ),
            next_import_rate=3.49,
            electricity_standing_charge=53.7,
            off_peak=stamp.time() >= time(23, 30) or stamp.hour == 0,
            intelligent_slot=False,
            house_load_kw=0.0,
            solar_power_kw=0.0,
        )
        for stamp in timestamps
    ]


def _config(agile):
    return agile.SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        battery_initial_percent=18.544,
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


def _rates(agile, snapshots):
    return [
        agile.AgileRate(
            "AGILE-OUTGOING-TEST",
            "E-1R-AGILE-OUTGOING-TEST-L",
            12.0,
            item.timestamp,
            item.timestamp + timedelta(minutes=30),
        )
        for item in snapshots
    ]


def test_2330_charge_is_carried_across_midnight() -> None:
    agile, _, handoff, tariff_module, _ = _load_modules()
    records = _snapshots(agile)
    config = _config(agile)
    manager = object.__new__(handoff.TomorrowSocHandoffAgileSmartExportManager)
    manager._simulation = agile.SimulationEngine()
    manager._rates = _rates(agile, records)
    manager._daily = {}
    manager._prepare_replay_continuity(records)

    expected_exact_midnight = 18.544 + (3.325 / 56.42 * 100.0)
    assert round(expected_exact_midnight, 3) == 24.437

    first = manager._compare_day(
        records[1:2], config, _tariff(tariff_module), 18.544, 18.544, None
    )
    midnight_soc = float(first["agile_smart_export"]["ending_soc_percent"])
    assert midnight_soc == 24.4
    assert "2026-08-27" in manager._midnight_replay_augmented_days

    second = manager._compare_day(
        records[2:], config, _tariff(tariff_module), midnight_soc, midnight_soc, None
    )
    assert round(float(second["agile_smart_export"]["ending_soc_percent"]), 1) == 30.3


def test_first_replay_day_uses_persisted_previous_soc() -> None:
    agile, _, handoff, tariff_module, _ = _load_modules()
    records = _snapshots(agile)[2:]
    config = _config(agile)
    manager = object.__new__(handoff.TomorrowSocHandoffAgileSmartExportManager)
    manager._simulation = agile.SimulationEngine()
    manager._rates = _rates(agile, records)
    manager._daily = {
        "2026-08-27": {
            "ready": True,
            "agile_smart_export": {"ending_soc_percent": 24.437},
            "full_kems_forecast": {"ending_soc_percent": 24.437},
        }
    }
    manager._prepare_replay_continuity(records)

    result = manager._compare_day(
        records, config, _tariff(tariff_module), 18.544, 18.544, None
    )
    assert manager._midnight_replay_seed_applied is True
    assert round(float(result["agile_smart_export"]["ending_soc_percent"]), 1) == 30.3


@dataclass(frozen=True)
class _FakeControl:
    desired_work_mode: str
    desired_charge_power_kw: float
    operating_reason: str


def test_shadow_cheap_charge_target_mirrors_canonical_control() -> None:
    _, _, _, _, charge_truth = _load_modules()
    candidate = _FakeControl("Self Use", 0.0, "agile_shadow_cheap_charge")
    control = _FakeControl("Force Charge", 7.0, "confirmed_cheap_charge")
    context = {
        "dispatch_mode": "cheap_charge",
        "optimizer_target": {"battery_export_kw": 0.0, "total_discharge_kw": 0.0},
        "parity": {"export_target_matches_optimizer": True},
        "parity_passed": True,
    }

    corrected, updated = charge_truth.reconcile_cheap_charge_target(
        candidate, context, control
    )
    assert corrected is not None
    assert corrected.desired_charge_power_kw == 7.0
    assert corrected.desired_work_mode == "Force Charge"
    assert updated["optimizer_target"]["charge_kw"] == 7.0
    assert updated["cheap_charge_target_reconciled"] is True
    assert updated["charge_target_source"] == "canonical ControlState"
    assert updated["parity_passed"] is True


def test_shadow_truth_is_reporting_only_and_runtime_installed() -> None:
    source = (INTEGRATION / "agile_shadow_charge_truth.py").read_text()
    runtime = (INTEGRATION / "agile_smart_export_runtime.py").read_text()

    assert 'getattr(control, "desired_charge_power_kw"' in source
    assert "install_shadow_charge_truth()" in runtime
    assert runtime.index("install_shadow_charge_truth()") > runtime.index(
        "install_alpha7_compatibility()"
    )
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware" not in source


def test_alpha837_version_and_release_scope() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    version = str(manifest["version"])
    assert version.startswith("0.8.0-alpha8.")
    assert int(version.rsplit(".", 1)[-1]) >= 37
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
