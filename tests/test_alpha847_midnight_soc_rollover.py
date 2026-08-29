"""Regression coverage for Alpha8.47 settled midnight SOC rollover."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import types
from datetime import date, datetime, time
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

    rollover = importlib.import_module("custom_components.kems.agile_midnight_rollover")
    tariff_module = importlib.import_module("custom_components.kems.tariff")
    return agile, rollover, tariff_module


def _snapshots(agile):
    timestamps = [
        datetime(2026, 8, 28, 23, 30, 49, tzinfo=LONDON),
        datetime(2026, 8, 28, 23, 59, 20, tzinfo=LONDON),
        datetime(2026, 8, 29, 0, 0, 41, tzinfo=LONDON),
        datetime(2026, 8, 29, 0, 30, 0, tzinfo=LONDON),
    ]
    return [
        agile.Snapshot(
            timestamp=stamp,
            current_import_rate=3.49,
            next_import_rate=3.49,
            electricity_standing_charge=53.7,
            off_peak=True,
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
        battery_initial_percent=10.0,
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


def _rates(agile, records):
    first = records[0].timestamp
    return [
        agile.AgileRate(
            "AGILE-OUTGOING-TEST",
            "E-1R-AGILE-OUTGOING-TEST-L",
            12.0,
            first,
            datetime(2026, 8, 29, 0, 30, 49, tzinfo=LONDON),
        )
    ]


def _manager(agile, rollover, records):
    manager = object.__new__(rollover.MidnightRolloverAgileSmartExportManager)
    manager._simulation = agile.SimulationEngine()
    manager._rates = _rates(agile, records)
    manager._daily = {}
    manager._settled_midnight_rollover_seed = None
    manager._midnight_rollover_now_date = date(2026, 8, 29)
    manager._settled_midnight_seed_applied = False
    manager._settled_midnight_stale_replay_soc = None
    manager._synthetic_midnight_boundary_days = set()
    manager._prepare_replay_continuity(records)
    return manager


def test_missing_exact_midnight_sample_gets_timestamp_only_boundary() -> None:
    agile, rollover, tariff_module = _load_modules()
    records = _snapshots(agile)
    manager = _manager(agile, rollover, records)

    boundary = manager._midnight_replay_boundaries[date(2026, 8, 28)]
    assert boundary.timestamp == datetime(2026, 8, 29, 0, 0, tzinfo=LONDON)
    assert boundary.house_load_kw == records[2].house_load_kw
    assert "2026-08-28" in manager._synthetic_midnight_boundary_days

    result = manager._compare_day(
        records[:2],
        _config(agile),
        _tariff(tariff_module),
        18.544,
        18.544,
        None,
    )
    expected = 18.544 + (7.0 * (29 * 60 + 11) / 3600 * 0.95 / 56.42 * 100)
    assert (
        abs(float(result["agile_smart_export"]["ending_soc_percent"]) - expected) < 0.1
    )
    assert "2026-08-28" in manager._midnight_replay_augmented_days


def test_settled_midnight_seed_overrides_stale_previous_day_replay_soc() -> None:
    agile, rollover, tariff_module = _load_modules()
    records = _snapshots(agile)
    manager = _manager(agile, rollover, records)
    manager._settled_midnight_rollover_seed = {
        "source_date": "2026-08-28",
        "target_date": "2026-08-29",
        "generated_at": "2026-08-28T23:59:20+01:00",
        "basis": rollover.ACTIVE_CHEAP_HANDOFF_BASIS,
        "source": rollover.SETTLED_ROLLOVER_SOURCE,
        "settled_current_soc_percent": 6.008,
        "agile_midnight_soc_percent": 11.738,
        "hardware_writes": "blocked",
    }

    result = manager._compare_day(
        records[:2],
        _config(agile),
        _tariff(tariff_module),
        14.4,
        14.4,
        None,
    )
    agile_result = result["agile_smart_export"]
    assert float(agile_result["pre_rollover_replay_ending_soc_percent"]) > 14.4
    assert agile_result["ending_soc_percent"] == 11.738
    assert agile_result["soc_rollover_source"] == rollover.SETTLED_ROLLOVER_SOURCE
    assert manager._settled_midnight_seed_applied is True


def test_rollover_seed_cannot_change_soc_before_target_day_begins() -> None:
    agile, rollover, tariff_module = _load_modules()
    records = _snapshots(agile)
    manager = _manager(agile, rollover, records)
    manager._midnight_rollover_now_date = date(2026, 8, 28)
    manager._settled_midnight_rollover_seed = {
        "source_date": "2026-08-28",
        "target_date": "2026-08-29",
        "agile_midnight_soc_percent": 11.738,
    }

    result = manager._compare_day(
        records[:2],
        _config(agile),
        _tariff(tariff_module),
        6.008,
        6.008,
        None,
    )
    assert result["agile_smart_export"]["ending_soc_percent"] != 11.738
    assert manager._settled_midnight_seed_applied is False


def test_only_active_cheap_handoff_is_persisted_as_rollover_authority() -> None:
    _, rollover, _ = _load_modules()
    manager = object.__new__(rollover.MidnightRolloverAgileSmartExportManager)
    manager._settled_midnight_rollover_seed = None
    manager._midnight_rollover_seed_dirty = False
    manager._state = {
        "tomorrow_soc_handoff": {
            "agile": {
                "basis": rollover.ACTIVE_CHEAP_HANDOFF_BASIS,
                "handoff_end": "2026-08-29T00:00:00+01:00",
                "midnight_soc_percent": 11.738,
            }
        },
        "settled_soc_handoff_reconciliation": {
            "settled_current_soc_percent": 6.008,
        },
    }
    now = datetime(2026, 8, 28, 23, 30, 49, tzinfo=LONDON)
    manager._capture_active_cheap_rollover_seed(now)

    seed = manager._settled_midnight_rollover_seed
    assert seed is not None
    assert seed["source_date"] == "2026-08-28"
    assert seed["target_date"] == "2026-08-29"
    assert seed["settled_current_soc_percent"] == 6.008
    assert seed["agile_midnight_soc_percent"] == 11.738
    assert manager._midnight_rollover_seed_dirty is True

    manager._midnight_rollover_seed_dirty = False
    manager._state["tomorrow_soc_handoff"]["agile"][
        "basis"
    ] = "forecast projected SOC at cheap start"
    manager._state["tomorrow_soc_handoff"]["agile"]["midnight_soc_percent"] = 99.0
    manager._capture_active_cheap_rollover_seed(now)
    assert (
        manager._settled_midnight_rollover_seed["agile_midnight_soc_percent"] == 11.738
    )
    assert manager._midnight_rollover_seed_dirty is False


def test_alpha847_runtime_scope_and_release_metadata() -> None:
    runtime = (INTEGRATION / "agile_smart_export_runtime.py").read_text()
    rollover_source = (INTEGRATION / "agile_midnight_rollover.py").read_text()
    flow_source = (INTEGRATION / "agile_flow_presentation.py").read_text()
    canonical_source = (INTEGRATION / "agile_canonical_flow_accounting.py").read_text()
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    direct_flow = "FlowPresentationAgileSmartExportManager" in runtime
    canonical_owner = (
        "EfficientAgileSmartExportManager = "
        "CanonicalFlowAccountingAgileSmartExportManager"
    )
    canonical_flow = (
        canonical_owner in runtime
        and "FlowPresentationAgileSmartExportManager" in canonical_source
        and "class CanonicalFlowAccountingAgileSmartExportManager" in canonical_source
    )
    assert direct_flow or canonical_flow
    assert "MidnightRolloverAgileSmartExportManager" in flow_source
    assert "SettledCurrentDayAgileSmartExportManager" not in runtime
    assert ".services.async_call(" not in rollover_source
    assert "providers.foxess" not in rollover_source
    assert '"hardware_writes": "blocked"' in rollover_source
    assert ".services.async_call(" not in canonical_source
    assert "providers.foxess" not in canonical_source
    assert 'hardware_writes": "blocked' in canonical_source

    version = str(manifest["version"])
    assert version.startswith("0.8.0-alpha8.")
    assert int(version.rsplit(".", 1)[-1]) >= 47
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
    ]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.7"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
