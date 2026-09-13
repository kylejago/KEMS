"""Alpha9.34 explicit battery-installation authority regression tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BATTERY_INSTALLATION = KEMS / "battery_installation.py"
CONST = KEMS / "const.py"
SWITCH = KEMS / "switch.py"


def _load_battery_installation():
    """Load the pure battery contract without importing Home Assistant."""
    custom_components = ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = ModuleType("custom_components.kems")
    package.__path__ = [str(KEMS)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.kems"] = package

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.kems.const",
        CONST,
    )
    assert const_spec is not None
    assert const_spec.loader is not None
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)

    spec = importlib.util.spec_from_file_location(
        "custom_components.kems.battery_installation",
        BATTERY_INSTALLATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_battery_installation_defaults_fail_closed() -> None:
    module = _load_battery_installation()
    assert module.battery_installed_from_options({}) is False
    assert module.battery_installed_from_options({"battery_installed": True}) is True


def test_no_battery_sentinel_is_advisory_when_not_installed() -> None:
    module = _load_battery_installation()
    assessment = module.assess_battery_values(
        installed=False,
        soc_percent=0,
        power_kw=0,
        voltage_v=-1.1,
        current_a=0,
    )
    assert assessment.state == "Not expected"
    assert assessment.healthy is None
    assert assessment.no_battery_sentinel_detected is True
    assert assessment.setting_telemetry_mismatch is False


def test_installed_battery_turns_same_sentinel_into_fault() -> None:
    module = _load_battery_installation()
    assessment = module.assess_battery_values(
        installed=True,
        soc_percent=0,
        power_kw=0,
        voltage_v=-1.1,
        current_a=0,
    )
    assert assessment.state == "Fault"
    assert assessment.healthy is False
    assert assessment.no_battery_sentinel_detected is True
    assert assessment.setting_telemetry_mismatch is True
    assert "sentinel" in assessment.detail


def test_zero_soc_alone_is_not_a_fault() -> None:
    module = _load_battery_installation()
    assessment = module.assess_battery_values(
        installed=True,
        soc_percent=0,
        power_kw=0,
        voltage_v=410,
        current_a=0,
    )
    assert assessment.state == "Healthy"
    assert assessment.healthy is True
    assert assessment.no_battery_sentinel_detected is False


def test_installed_battery_requires_credible_numeric_telemetry() -> None:
    module = _load_battery_installation()
    assessment = module.assess_battery_values(
        installed=True,
        soc_percent=None,
        power_kw=None,
        voltage_v=None,
        current_a=None,
    )
    assert assessment.state == "Fault"
    assert assessment.healthy is False
    assert "SOC" in assessment.detail
    assert "voltage" in assessment.detail


def test_configuration_switch_persists_explicit_installation_option() -> None:
    source = SWITCH.read_text(encoding="utf-8")
    assert "class KEMSBatteryInstalledSwitch" in source
    assert '_attr_name = "Battery installed"' in source
    assert "EntityCategory.CONFIG" in source
    assert "CONF_BATTERY_INSTALLED" in source
    assert "async_set_runtime_option" in source
    assert "install_battery_installation_contract()" in source


def test_explicit_setting_changes_commissioning_only_not_write_authority() -> None:
    source = BATTERY_INSTALLATION.read_text(encoding="utf-8")
    assert 'payload["battery_installation_source"] = "explicit_setting"' in source
    assert 'payload["battery_installation_status"]' in source
    assert 'payload["battery_commissioning_status"]' in source
    assert 'payload["ready_for_control"] = False' in source
    assert 'payload["real_hardware_writes"] = "blocked"' in source
    assert "battery_telemetry_health" in source
