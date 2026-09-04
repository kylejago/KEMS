"""Pure FoxESS command-shadow translation for KEMS.

This module deliberately contains no Home Assistant service calls, Modbus client,
or write path.  It translates the already-authoritative KEMS ControlState into
the FoxESS Modbus v1.15.0 control surface KEMS would eventually request, then
compares that proposal with read-only observed entity state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .models import ControlState

PASS = "PASS"
WAIT = "WAIT"
DIFF = "DIFF"
MATCH = "MATCH"


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_number(expected: float, observed: object, tolerance: float = 0.05) -> bool | None:
    actual = _number(observed)
    if actual is None:
        return None
    return abs(actual - expected) <= tolerance


def _field_parity(
    expected: object,
    observed: object,
    *,
    tolerance: float | None = None,
) -> dict[str, Any]:
    if expected is None:
        return {
            "expected": None,
            "observed": observed,
            "status": "NOT_REQUIRED",
        }
    if observed is None:
        return {"expected": expected, "observed": None, "status": WAIT}
    if tolerance is not None and isinstance(expected, (int, float)):
        same = _same_number(float(expected), observed, tolerance)
        status = WAIT if same is None else MATCH if same else DIFF
    else:
        status = MATCH if str(observed).casefold() == str(expected).casefold() else DIFF
    return {"expected": expected, "observed": observed, "status": status}


def build_foxess_command_shadow(
    control: ControlState,
    observed: Mapping[str, object] | None = None,
    *,
    export_limit_kw: float = 7.0,
) -> dict[str, Any]:
    """Translate one KEMS decision into a zero-write FoxESS command proposal.

    FoxESS Modbus v1.15.0 exposes Force Charge and Force Discharge as virtual
    Work Mode options backed by its remote-control manager.  Force Charge Power
    and Force Discharge Power are native kW controls.  The KH_133 export limit
    is native W.  KEMS records those exact units here but never invokes them.
    """
    observed_values = dict(observed or {})
    desired_export = max(control.desired_battery_export_power_kw, 0.0)
    desired_charge = max(control.desired_charge_power_kw, 0.0)

    translation_status = PASS
    translation_reason = "KEMS decision has an exact reviewed FoxESS shadow representation"
    proposed_work_mode: str | None = None
    force_charge_power_kw: float | None = None
    force_discharge_power_kw: float | None = None

    if control.operating_reason == "emergency_stop":
        translation_status = WAIT
        translation_reason = "Emergency stop forbids a new FoxESS command"
    elif not control.plan_safe:
        translation_status = WAIT
        translation_reason = "Unsafe KEMS plan must not be translated into a hardware command"
    elif control.desired_work_mode in {"No change", "Stop KEMS writes"}:
        translation_status = WAIT
        translation_reason = "KEMS explicitly requests no hardware state change"
    elif control.desired_work_mode == "Force Charge":
        proposed_work_mode = "Force Charge"
        force_charge_power_kw = round(desired_charge, 3)
    elif desired_export > 0.001:
        # The upstream Force Discharge Power control is documented as the power
        # fed into the grid.  KEMS therefore translates deliberate battery
        # export only; battery-to-home remains an observed/self-use flow, not a
        # separately invented FoxESS command.
        proposed_work_mode = "Force Discharge"
        force_discharge_power_kw = round(desired_export, 3)
    elif control.desired_work_mode in {"Self Use", "Feed-in First"}:
        proposed_work_mode = control.desired_work_mode
    elif control.desired_work_mode == "Self Use / EPS":
        translation_status = WAIT
        translation_reason = (
            "EPS/island fallback semantics require commissioned inverter-state proof; "
            "Alpha8.79 will not guess a grid-connected work-mode write"
        )
    else:
        translation_status = WAIT
        translation_reason = f"Unreviewed KEMS work mode: {control.desired_work_mode}"

    proposed_export_limit_w = round(
        (export_limit_kw if control.desired_grid_export_allowed else 0.0) * 1000
    )
    proposed_min_soc = round(control.desired_min_soc_percent, 1)

    proposed = {
        "work_mode": proposed_work_mode,
        "force_charge_power_kw": force_charge_power_kw,
        "force_discharge_power_kw": force_discharge_power_kw,
        "min_soc_percent": proposed_min_soc,
        "export_power_limit_w": proposed_export_limit_w,
        "charge_enabled": bool(proposed_work_mode == "Force Charge" and desired_charge > 0),
        "discharge_enabled": bool(
            proposed_work_mode == "Force Discharge" and desired_export > 0
        ),
        "grid_export_allowed": bool(control.desired_grid_export_allowed),
        "remote_control_required": proposed_work_mode in {"Force Charge", "Force Discharge"},
        "schedule_strategy": "FoxESS remote-control virtual work mode; no KEMS schedule write",
    }

    parity = {
        "work_mode": _field_parity(proposed_work_mode, observed_values.get("work_mode")),
        "force_charge_power_kw": _field_parity(
            force_charge_power_kw,
            observed_values.get("force_charge_power"),
            tolerance=0.05,
        ),
        "force_discharge_power_kw": _field_parity(
            force_discharge_power_kw,
            observed_values.get("force_discharge_power"),
            tolerance=0.05,
        ),
        "min_soc_percent": _field_parity(
            proposed_min_soc,
            observed_values.get("min_soc"),
            tolerance=0.5,
        ),
        "export_power_limit_w": _field_parity(
            proposed_export_limit_w,
            observed_values.get("export_power_limit"),
            tolerance=1.0,
        ),
    }
    required = [
        value["status"]
        for value in parity.values()
        if value["status"] != "NOT_REQUIRED"
    ]
    if translation_status != PASS:
        observed_parity = WAIT
        parity_reason = translation_reason
    elif any(status == WAIT for status in required):
        observed_parity = WAIT
        parity_reason = "Waiting for the commissioned FoxESS command entities"
    elif any(status == DIFF for status in required):
        observed_parity = DIFF
        parity_reason = (
            "Observed FoxESS state differs from the proposed command; this is expected "
            "while Alpha8.79 is shadow-only and sends no commands"
        )
    else:
        observed_parity = MATCH
        parity_reason = "Observed FoxESS state already matches the proposed command"

    desired = {
        "operating_reason": control.operating_reason,
        "desired_work_mode": control.desired_work_mode,
        "requested_charge_power_kw": round(desired_charge, 3),
        "desired_battery_to_home_power_kw": round(
            max(control.desired_battery_to_home_power_kw, 0.0), 3
        ),
        "deliberate_battery_export_power_kw": round(desired_export, 3),
        "requested_total_discharge_power_kw": round(
            max(control.desired_total_discharge_power_kw, 0.0), 3
        ),
        "requested_min_soc_percent": proposed_min_soc,
        "desired_grid_export_allowed": bool(control.desired_grid_export_allowed),
        "plan_safe": bool(control.plan_safe),
    }

    return {
        "scope": "translation/proof only",
        "reviewed_foxess_modbus_version": "1.15.0",
        "commands_permitted": False,
        "real_hardware_writes": "blocked",
        "maximum_allowed_stage": "shadow",
        "kems_decision": desired,
        "proposed_foxess_command": proposed,
        "observed_foxess_state": observed_values,
        "translation_status": translation_status,
        "translation_reason": translation_reason,
        "parity": parity,
        "parity_result": observed_parity,
        "parity_reason": parity_reason,
        "control_state_safety": {
            "real_backend_available": bool(control.real_backend_available),
            "commands_permitted": bool(control.commands_permitted),
            "control_enabled": bool(control.control_enabled),
            "commissioned": bool(control.commissioned),
        },
        "control_state": asdict(control),
    }
