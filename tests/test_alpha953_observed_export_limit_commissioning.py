"""Alpha9.53 observed FoxESS export-limit commissioning regressions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from kems_core import ControlState
from kems_core.foxess_command_shadow import WAIT, build_foxess_command_shadow

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha953_export_limit_test"


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


def _readback_binding() -> dict[str, object]:
    return {
        "status": "PASS",
        "entity_id": "number.kh7_export_power_limit",
        "readback_entity_id": "sensor.kh7_export_power_limit",
        "observation_entity_id": "sensor.kh7_export_power_limit",
        "observation_source": "sensor_readback",
        "candidate_readback_entity_ids": ["sensor.kh7_export_power_limit"],
    }


def _assess(observed_w: object, *, binding: dict[str, object] | None = None):
    return proof.assess_foxess_export_limit_readback(
        configured_export_limit_kw=6.4,
        selected_device_id="kh7-device",
        binding=_readback_binding() if binding is None else binding,
        observed_export_limit_w=observed_w,
    )


def test_observed_export_limit_at_kems_ceiling_passes() -> None:
    result = _assess(6400.0)

    assert result["status"] == "PASS"
    assert result["required"] is True
    assert "FoxESS hardware ceiling=6.400 kW" in result["detail"]
    assert "KEMS ceiling=6.400 kW" in result["detail"]
    assert result["effective_export_limit_kw"] == 6.4


def test_observed_export_limit_below_kems_ceiling_fails_closed() -> None:
    result = _assess(5000.0)

    assert result["status"] == "FAIL"
    assert result["required"] is True
    assert "FoxESS hardware ceiling=5.000 kW" in result["detail"]
    assert "KEMS ceiling=6.400 kW exceeds" in result["detail"]
    assert result["effective_export_limit_kw"] == 5.0


def test_live_like_14_5_kw_readback_is_usable_hardware_ceiling() -> None:
    # Alpha9.54 supersedes Alpha9.53's equality assumption: the FoxESS setting
    # may be higher than the user-selected KEMS ceiling.
    result = _assess(14500.0)

    assert result["status"] == "PASS"
    assert result["required"] is True
    assert "FoxESS hardware ceiling=14.500 kW" in result["detail"]
    assert "KEMS ceiling=6.400 kW" in result["detail"]
    assert result["effective_export_limit_kw"] == 6.4


def test_missing_or_unusable_export_limit_readback_waits() -> None:
    missing = _assess(None)
    assert missing["status"] == "WAIT"
    assert missing["required"] is True

    no_sensor = _assess(
        6400.0,
        binding={
            "status": "PASS",
            "entity_id": "number.kh7_export_power_limit",
            "readback_entity_id": None,
            "observation_source": "command_entity",
        },
    )
    assert no_sensor["status"] == "WAIT"
    assert "dedicated read-only" in no_sensor["detail"]


def test_ambiguous_or_unbound_export_limit_readback_waits() -> None:
    ambiguous = _assess(
        6400.0,
        binding={
            "status": "WAIT",
            "candidate_readback_entity_ids": [
                "sensor.kh7_export_power_limit",
                "sensor.kh7_export_power_limit_2",
            ],
        },
    )
    assert ambiguous["status"] == "WAIT"
    assert ambiguous["required"] is True

    no_device = proof.assess_foxess_export_limit_readback(
        configured_export_limit_kw=6.4,
        selected_device_id=None,
        binding=_readback_binding(),
        observed_export_limit_w=6400.0,
    )
    assert no_device["status"] == "WAIT"


def test_shadow_parity_wording_is_release_neutral_and_writes_remain_blocked() -> None:
    control = ControlState(
        operating_reason="normal",
        desired_work_mode="Self Use",
        desired_battery_to_home_power_kw=0.581,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.581,
        desired_grid_export_allowed=False,
        desired_min_soc_percent=15.0,
        data_fresh=True,
        plan_safe=True,
        control_enabled=False,
        commissioned=False,
        real_backend_available=False,
        commands_permitted=False,
        blocked_reason="Virtual backend only",
    )
    result = build_foxess_command_shadow(
        control,
        observed={
            "work_mode": "Self Use",
            "min_soc_on_grid_percent": 10.0,
            "export_power_limit_w": 14500.0,
        },
        export_limit_kw=6.4,
    )

    assert result["parity_result"] == "DIFF"
    assert "Alpha8.79" not in result["parity_reason"]
    assert "hardware control remains disabled" in result["parity_reason"]
    proposed = result["proposed_foxess_command"]
    assert proposed["export_power_limit_w"] == 0
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["discharge_enabled"] is False
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"
    assert result["maximum_allowed_stage"] == "shadow"


def test_island_shadow_wording_is_release_neutral_and_fails_closed() -> None:
    island = ControlState(
        operating_reason="island",
        desired_work_mode="Self Use / EPS",
        desired_grid_export_allowed=False,
        island_mode_active=True,
        data_fresh=True,
        plan_safe=True,
        control_enabled=False,
        commissioned=False,
        real_backend_available=False,
        commands_permitted=False,
    )

    result = build_foxess_command_shadow(island, export_limit_kw=6.4)

    assert result["translation_status"] == WAIT
    assert "Alpha8.79" not in result["translation_reason"]
    assert "will not guess" in result["translation_reason"]
    assert result["proposed_foxess_command"]["export_power_limit_w"] == 0
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"
