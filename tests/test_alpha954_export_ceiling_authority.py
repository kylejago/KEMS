"""Alpha9.54 installer/FoxESS versus KEMS export-ceiling regressions."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from kems_core import ControlState
from kems_core.foxess_command_shadow import build_foxess_command_shadow

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha954_export_limit_test"
TRANSLATIONS = KEMS_ROOT / "translations" / "en.json"


def _load_export_limit_module():
    package = ModuleType(PACKAGE)
    package.__path__ = [str(KEMS_ROOT)]
    sys.modules[PACKAGE] = package

    shadow = ModuleType(f"{PACKAGE}.foxess_command_shadow")
    shadow.build_foxess_command_shadow_snapshot = lambda *_args, **_kwargs: {}
    sys.modules[shadow.__name__] = shadow

    name = f"{PACKAGE}.commissioning_export_limit"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS_ROOT / "commissioning_export_limit.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


proof = _load_export_limit_module()


def _binding() -> dict[str, object]:
    return {
        "status": "PASS",
        "entity_id": "number.kh7_export_power_limit",
        "readback_entity_id": "sensor.kh7_export_power_limit",
        "observation_entity_id": "sensor.kh7_export_power_limit",
        "observation_source": "sensor_readback",
        "candidate_readback_entity_ids": ["sensor.kh7_export_power_limit"],
    }


def _assess(kems_kw: float, observed_w: object):
    return proof.assess_foxess_export_limit_readback(
        configured_export_limit_kw=kems_kw,
        selected_device_id="kh7-device",
        binding=_binding(),
        observed_export_limit_w=observed_w,
    )


def _export_control(export_kw: float, *, allowed: bool = True) -> ControlState:
    return ControlState(
        operating_reason="agile_rolling_economic_preemptive_export",
        desired_work_mode="Feed-in First" if allowed else "Self Use",
        desired_battery_to_home_power_kw=0.656,
        desired_battery_export_power_kw=export_kw if allowed else 0.0,
        desired_total_discharge_power_kw=(0.656 + export_kw) if allowed else 0.656,
        desired_grid_export_allowed=allowed,
        desired_min_soc_percent=15.0,
        data_fresh=True,
        plan_safe=True,
        control_enabled=False,
        commissioned=False,
        real_backend_available=False,
        commands_permitted=False,
        blocked_reason="Virtual backend only",
    )


def test_live_14_5_kw_foxess_ceiling_allows_lower_6_4_kw_kems_ceiling() -> None:
    result = _assess(6.4, 14500.0)

    assert result["status"] == "PASS"
    assert result["foxess_hardware_limit_kw"] == 14.5
    assert result["kems_export_limit_kw"] == 6.4
    assert result["effective_export_limit_kw"] == 6.4
    assert "FoxESS hardware ceiling=14.500 kW" in result["detail"]
    assert "KEMS ceiling=6.400 kW" in result["detail"]


def test_equal_foxess_and_kems_ceiling_passes() -> None:
    result = _assess(6.4, 6400.0)

    assert result["status"] == "PASS"
    assert result["effective_export_limit_kw"] == 6.4


def test_kems_ceiling_above_foxess_hardware_ceiling_fails_closed() -> None:
    result = _assess(6.4, 5000.0)

    assert result["status"] == "FAIL"
    assert result["foxess_hardware_limit_kw"] == 5.0
    assert result["effective_export_limit_kw"] == 5.0
    assert (
        "KEMS ceiling=6.400 kW exceeds FoxESS hardware ceiling=5.000 kW"
        in result["detail"]
    )


def test_zero_kems_export_ceiling_is_valid_and_effective_zero() -> None:
    result = _assess(0.0, 14500.0)

    assert result["status"] == "PASS"
    assert result["effective_export_limit_kw"] == 0.0


def test_shadow_uses_lower_kems_ceiling_when_foxess_allows_more() -> None:
    result = build_foxess_command_shadow(
        _export_control(5.744),
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )

    authority = result["export_limit_authority"]
    proposed = result["proposed_foxess_command"]
    assert authority["foxess_hardware_ceiling_kw"] == 14.5
    assert authority["kems_user_ceiling_kw"] == 6.4
    assert authority["effective_ceiling_kw"] == 6.4
    assert result["effective_export_limit_kw"] == 6.4
    assert proposed["export_power_limit_w"] == 6400
    assert proposed["force_discharge_power_kw"] == 5.744
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"


def test_shadow_clamps_to_lower_foxess_ceiling_even_before_commissioning_fails(
) -> None:
    result = build_foxess_command_shadow(
        _export_control(5.744),
        observed={"export_power_limit_w": 5000.0},
        export_limit_kw=6.4,
    )

    proposed = result["proposed_foxess_command"]
    assert result["effective_export_limit_kw"] == 5.0
    assert proposed["export_power_limit_w"] == 5000
    assert proposed["force_discharge_power_kw"] == 5.0
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"


def test_no_export_policy_still_proposes_zero_with_14_5_kw_foxess_ceiling() -> None:
    result = build_foxess_command_shadow(
        _export_control(5.744, allowed=False),
        observed={"work_mode": "Self Use", "export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )

    proposed = result["proposed_foxess_command"]
    assert result["effective_export_limit_kw"] == 6.4
    assert proposed["export_power_limit_w"] == 0
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["grid_export_allowed"] is False
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"


def test_options_call_the_setting_kems_maximum_export() -> None:
    translations = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    battery = translations["options"]["step"]["battery"]

    assert battery["data"]["export_limit_kw"] == "KEMS maximum export (kW)"
    description = battery["data_description"]["export_limit_kw"]
    assert "lower than the FoxESS installer/current hardware limit" in description
    assert "never widens the FoxESS limit" in description
