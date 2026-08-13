"""Provider-level tests for Home Assistant source report freshness."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

from kems_core import calculate_battery_power_kw, normalise_grid_power

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _load_foxess_provider(monkeypatch):
    """Load the provider with a minimal Home Assistant state-machine stub."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    const = ModuleType("homeassistant.const")
    util = ModuleType("homeassistant.util")
    dt = ModuleType("homeassistant.util.dt")

    class State:
        def __init__(
            self,
            state: str,
            *,
            unit: str = "W",
            last_reported: datetime = NOW,
        ) -> None:
            self.state = state
            self.attributes = {"unit_of_measurement": unit}
            self.last_updated = last_reported
            self.last_reported = last_reported

    core.HomeAssistant = object
    core.State = State
    const.ATTR_UNIT_OF_MEASUREMENT = "unit_of_measurement"
    const.STATE_OFF = "off"
    const.STATE_ON = "on"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"
    dt.now = lambda: NOW
    util.dt = dt
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.const": const,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    package_name = "kems_freshness_provider_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    providers = ModuleType(f"{package_name}.providers")
    providers.__path__ = [str(INTEGRATION / "providers")]
    core_alias = ModuleType(f"{package_name}.kems_core")
    core_alias.calculate_battery_power_kw = calculate_battery_power_kw
    core_alias.normalise_grid_power = normalise_grid_power
    entity_map = ModuleType(f"{package_name}.providers.entity_map")
    entity_map.KEMSEntities = object
    for name, module in {
        package_name: package,
        f"{package_name}.providers": providers,
        f"{package_name}.kems_core": core_alias,
        f"{package_name}.providers.entity_map": entity_map,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    loaded = {}
    for module_name, path in (
        ("providers.base", INTEGRATION / "providers" / "base.py"),
        ("providers.foxess", INTEGRATION / "providers" / "foxess.py"),
    ):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(qualified, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, qualified, module)
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded["providers.foxess"], State


def test_foxess_provider_rejects_a_stale_live_meter(monkeypatch) -> None:
    """A still-valid numeric state is unusable after its report timeout."""
    foxess, State = _load_foxess_provider(monkeypatch)
    stale_time = NOW - timedelta(minutes=10)
    meter = State("3222", last_reported=stale_time)
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: meter))
    entities = SimpleNamespace(
        house_load_kw="sensor.live_meter",
        battery_soc=None,
        battery_power_kw=None,
        battery_voltage=None,
        battery_current=None,
        solar_power_kw=None,
        grid_import_kw="sensor.live_meter",
        grid_export_kw=None,
    )

    state = foxess.FoxESSProvider(
        hass,
        entities,
        stale_data_seconds=180,
    ).get_state(NOW)

    assert state.house_load_kw is None
    assert state.grid_import_kw is None
    assert state.raw_grid_import_kw is None
    assert state.source_age_seconds["house_load_kw"] == 600.0
    assert state.source_age_seconds["grid_import_kw"] == 600.0
    assert state.stale_fields == ("grid_import_kw", "house_load_kw")
    assert state.source_data_age_seconds == 600.0


def test_foxess_provider_accepts_recent_same_value_report(monkeypatch) -> None:
    """last_reported prevents an unchanged numeric value being falsely stale."""
    foxess, State = _load_foxess_provider(monkeypatch)
    meter = State("3222", last_reported=NOW - timedelta(seconds=45))
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: meter))
    entities = SimpleNamespace(
        house_load_kw="sensor.live_meter",
        battery_soc=None,
        battery_power_kw=None,
        battery_voltage=None,
        battery_current=None,
        solar_power_kw=None,
        grid_import_kw="sensor.live_meter",
        grid_export_kw=None,
    )

    state = foxess.FoxESSProvider(
        hass,
        entities,
        stale_data_seconds=180,
    ).get_state(NOW)

    assert state.house_load_kw == 3.222
    assert state.grid_import_kw == 3.222
    assert state.stale_fields == ()
    assert state.source_data_age_seconds == 45.0


def _load_octopus_provider(monkeypatch):
    """Load the Octopus provider with a minimal Home Assistant state stub."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    const = ModuleType("homeassistant.const")
    util = ModuleType("homeassistant.util")
    dt = ModuleType("homeassistant.util.dt")

    class State:
        def __init__(
            self,
            state: str,
            *,
            unit: str = "",
            last_reported: datetime = NOW,
        ) -> None:
            self.state = state
            self.attributes = {"unit_of_measurement": unit}
            self.last_updated = last_reported
            self.last_reported = last_reported

    core.HomeAssistant = object
    core.State = State
    const.ATTR_UNIT_OF_MEASUREMENT = "unit_of_measurement"
    const.STATE_OFF = "off"
    const.STATE_ON = "on"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"
    dt.now = lambda: NOW
    dt.parse_datetime = datetime.fromisoformat
    util.dt = dt
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.const": const,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    package_name = "kems_tariff_freshness_provider_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    providers = ModuleType(f"{package_name}.providers")
    providers.__path__ = [str(INTEGRATION / "providers")]
    entity_map = ModuleType(f"{package_name}.providers.entity_map")
    entity_map.KEMSEntities = object
    for name, module in {
        package_name: package,
        f"{package_name}.providers": providers,
        f"{package_name}.providers.entity_map": entity_map,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    loaded = {}
    for module_name, path in (
        ("providers.base", INTEGRATION / "providers" / "base.py"),
        ("providers.octopus", INTEGRATION / "providers" / "octopus.py"),
    ):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(qualified, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, qualified, module)
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded["providers.octopus"], State


def _octopus_entities(**overrides):
    """Return an entity mapping with optional tariff-source overrides."""
    values = {
        "current_import_rate": None,
        "next_import_rate": None,
        "current_export_rate": None,
        "electricity_standing_charge": None,
        "off_peak": None,
        "intelligent_slot": None,
        "next_offpeak_start": None,
        "offpeak_end": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_octopus_provider_rejects_intelligent_slot_after_360_seconds(
    monkeypatch,
) -> None:
    """An Intelligent-slot report older than 360 seconds must fail closed."""
    octopus, State = _load_octopus_provider(monkeypatch)
    stale_slot = State("on", last_reported=NOW - timedelta(seconds=361))
    states = {"binary_sensor.slot": stale_slot}
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))

    state = octopus.OctopusProvider(
        hass,
        _octopus_entities(intelligent_slot="binary_sensor.slot"),
        stale_data_seconds=180,
    ).get_state(NOW)

    assert state.intelligent_slot is False
    assert state.source_age_seconds["intelligent_slot"] == 361.0
    assert state.stale_fields == ("intelligent_slot",)


def test_octopus_provider_accepts_intelligent_slot_at_359_seconds(
    monkeypatch,
) -> None:
    """A 359-second-old Intelligent slot remains within its source window."""
    octopus, State = _load_octopus_provider(monkeypatch)
    recent_slot = State("on", last_reported=NOW - timedelta(seconds=359))
    states = {"binary_sensor.slot": recent_slot}
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))

    state = octopus.OctopusProvider(
        hass,
        _octopus_entities(intelligent_slot="binary_sensor.slot"),
        stale_data_seconds=180,
    ).get_state(NOW)

    assert state.intelligent_slot is True
    assert state.source_age_seconds["intelligent_slot"] == 359.0
    assert state.stale_fields == ()


def test_octopus_provider_keeps_fast_tariff_sources_at_180_seconds(
    monkeypatch,
) -> None:
    """Only Intelligent integration fields receive the longer freshness window."""
    octopus, State = _load_octopus_provider(monkeypatch)
    reported = NOW - timedelta(seconds=181)
    states = {
        "binary_sensor.slot": State("on", last_reported=reported),
        "binary_sensor.off_peak": State("off", last_reported=reported),
        "sensor.next_start": State(
            "2026-08-13T22:30:00+00:00",
            last_reported=reported,
        ),
    }
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))

    state = octopus.OctopusProvider(
        hass,
        _octopus_entities(
            intelligent_slot="binary_sensor.slot",
            off_peak="binary_sensor.off_peak",
            next_offpeak_start="sensor.next_start",
        ),
        stale_data_seconds=180,
    ).get_state(NOW)

    assert state.intelligent_slot is True
    assert state.next_offpeak_start is not None
    assert state.off_peak is None
    assert state.stale_fields == ("off_peak",)
