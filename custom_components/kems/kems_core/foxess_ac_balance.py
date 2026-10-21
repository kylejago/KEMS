"""Read-only AC-side FoxESS balance correlation for KH series inverters.

RPower and Grid CT are AC quantities. InvBatPower is battery-side; it must not
be substituted for inverter AC output in a whole-site conservation equation.
FoxESS Load Power can be CALCULATED from RPower and CT, so agreement is not
independent electrical safety proof and never grants or restores write access.

The supplemental register observation is taken after the ordinary snapshot.
Report each register timestamp and reject mismatched polling cohorts.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def _power_kw(raw: Any) -> float | None:
    if not isinstance(raw, dict):
        return None
    power = _number(raw.get("value"))
    unit = str(raw.get("unit") or "").strip().casefold()
    if power is None:
        return None
    if unit == "w":
        return power / 1000.0
    if unit == "kw":
        return power
    return None


def assess_foxess_ac_side_sample(
    observation: Any,
    *,
    maximum_cohort_skew_seconds: float = 35.0,
    absolute_tolerance_kw: float = 0.25,
) -> dict[str, Any]:
    """Classify an AC boundary sample without granting control authority.

    KH Grid CT: positive export, negative import after foxess_modbus
    normalisation. Signed inverter RPower can be negative on charging.
    A passing computed house-load identity is NOT independent validation.
    """
    result: dict[str, Any] = {
        "status": "missing_probe",
        "informational_only": True,
        "independent_load_proven": False,
        "hardware_write_authorised": False,
        "boundary": "inverter AC output + grid import - grid export = site load",
        "load_caveat": "FoxESS Load Power may be derived from inverter AC and CT",
    }
    probe = getattr(observation, "foxess_balance_probe", None)
    if not isinstance(probe, dict):
        return result
    inverter = probe.get("inverter_ac_output")
    grid_ct = probe.get("grid_ct")
    if not isinstance(inverter, dict) or not isinstance(grid_ct, dict):
        return result
    inverter_kw = _power_kw(inverter)
    grid_ct_kw = _power_kw(grid_ct)
    house_kw = _number(getattr(observation, "house_load_kw", None))
    grid_import_kw = _number(getattr(observation, "grid_import_kw", None))
    grid_export_kw = _number(getattr(observation, "grid_export_kw", None))
    if None in (inverter_kw, grid_ct_kw, house_kw, grid_import_kw, grid_export_kw):
        result["status"] = "invalid_or_missing_power"
        return result
    assert inverter_kw is not None and grid_ct_kw is not None
    assert house_kw is not None
    assert grid_import_kw is not None and grid_export_kw is not None
    if house_kw < -0.05 or grid_import_kw < -0.05 or grid_export_kw < -0.05:
        result["status"] = "invalid_physical_power"
        return result

    snapshot_at = getattr(observation, "timestamp", None)
    probe_at = _when(probe.get("observed_after_snapshot_at"))
    inverter_at = _when(inverter.get("last_reported") or inverter.get("last_updated"))
    ct_at = _when(grid_ct.get("last_reported") or grid_ct.get("last_updated"))
    if (
        not isinstance(snapshot_at, datetime)
        or snapshot_at.tzinfo is None
        or probe_at is None
        or inverter_at is None
        or ct_at is None
    ):
        result["status"] = "missing_timestamps"
        return result
    skew = max(
        abs((probe_at - snapshot_at).total_seconds()),
        abs((inverter_at - snapshot_at).total_seconds()),
        abs((ct_at - snapshot_at).total_seconds()),
        abs((inverter_at - ct_at).total_seconds()),
    )
    result["cohort_skew_seconds"] = round(skew, 1)
    if (
        skew > maximum_cohort_skew_seconds
        or inverter_at > probe_at
        or ct_at > probe_at
        or probe_at < snapshot_at
    ):
        result["status"] = "not_time_aligned"
        return result
    ages = getattr(observation, "source_age_seconds", None)
    house_age = _number(ages.get("house_load_kw")) if isinstance(ages, dict) else None
    if house_age is None or not 0 <= house_age <= maximum_cohort_skew_seconds:
        result["status"] = "house_report_stale"
        return result
    if "house_load_kw" in set(getattr(observation, "stale_fields", ()) or ()):
        result["status"] = "house_report_stale"
        return result

    # No battery-side DC term in the AC equation. Grid CT is signed
    # (+ export, - import) in foxess_modbus normalised units.
    ac_site_load_kw = inverter_kw - grid_ct_kw
    ac_residual_kw = ac_site_load_kw - house_kw
    ct_expected_kw = grid_export_kw - grid_import_kw
    ct_residual_kw = grid_ct_kw - ct_expected_kw
    result.update(
        {
            "status": "ac_cross_check_pass",
            "inverter_ac_kw": round(inverter_kw, 3),
            "grid_ct_kw": round(grid_ct_kw, 3),
            "ac_implied_load_kw": round(ac_site_load_kw, 3),
            "foxess_reported_load_kw": round(house_kw, 3),
            "ac_load_residual_kw": round(ac_residual_kw, 3),
            "ct_split_residual_kw": round(ct_residual_kw, 3),
            "tolerance_kw": round(absolute_tolerance_kw, 3),
            "battery_dc_minus_inverter_ac_kw": (
                round(battery_kw - inverter_kw, 3)
                if (
                    battery_kw := _number(
                        getattr(observation, "battery_power_kw", None)
                    )
                )
                is not None
                else None
            ),
        }
    )
    if abs(ct_residual_kw) > absolute_tolerance_kw:
        result["status"] = "grid_ct_split_mismatch"
    elif abs(ac_residual_kw) > absolute_tolerance_kw:
        result["status"] = "ac_load_mismatch"
    return result


def paid_export_stage_ct_conflict(
    observation: Any, *, positive_is_discharge: bool = True
) -> bool:
    """Identify contradictory, *not disproven*, physical 1 kW export evidence.

    A KH7 may report roughly 1.4 kW inverter AC output, 1.5 kW battery
    discharge and 0.35 kW house load while its CT unexpectedly reports near
    zero export. This cannot prove grid export or a failed inverter write.
    It cannot make the commissioning gate pass or grant hardware authority.

    Apply only to recent, time-coherent, solar-low, battery-AC-agreeing
    observations. Missing or stale probes are NOT treated as a CT conflict.
    """
    check = assess_foxess_ac_side_sample(observation)
    if check["status"] != "ac_load_mismatch":
        return False
    residual = _number(check.get("ac_load_residual_kw"))
    inverter = _number(check.get("inverter_ac_kw"))
    house = _number(check.get("foxess_reported_load_kw"))
    grid_ct = _number(check.get("grid_ct_kw"))
    battery = _number(getattr(observation, "battery_power_kw", None))
    solar = _number(getattr(observation, "solar_power_kw", None))
    grid_export = _number(getattr(observation, "grid_export_kw", None))
    if None in (residual, inverter, house, grid_ct, battery, solar, grid_export):
        return False
    assert residual is not None and inverter is not None and house is not None
    assert grid_ct is not None and battery is not None and solar is not None
    assert grid_export is not None
    signed_battery = battery if positive_is_discharge else -battery
    stale = set(getattr(observation, "stale_fields", ()) or ())
    if {
        "battery_power_kw",
        "solar_power_kw",
        "house_load_kw",
        "grid_export_kw",
        "grid_import_kw",
    } & stale:
        return False
    return bool(
        0.75 < residual < 1.75
        and 1.0 <= inverter <= 2.5
        and 0.0 <= house <= 1.5
        and -0.2 <= grid_ct <= 0.2
        and grid_export < 0.2
        and solar < 0.5
        and signed_battery >= 0.25
        and abs(signed_battery + solar - inverter) <= 0.4
    )



def assess_foxess_ac_ct_transition(previous: Any, current: Any) -> dict[str, Any]:
    """Compare adjacent valid KH register cohorts without asserting CT fault.

    Only a formerly consistent grid-export reading followed by a contradictory,
    near-zero CT is considered a candidate. AC, battery, house load and PV must
    remain nearly steady. The two samples must be within 100 seconds; a normal
    inverter setpoint change, stale sensor or missing proof is not a CT fault.
    This evidence NEVER changes commissioning or inverter write authority.
    """
    result: dict[str, Any] = {
        "status": "no_comparable_transition",
        "informational_only": True,
        "ct_hardware_fault_proven": False,
        "independent_meter_proven": False,
        "hardware_write_authorised": False,
    }
    prior_at = getattr(previous, "timestamp", None)
    current_at = getattr(current, "timestamp", None)
    if (
        not isinstance(prior_at, datetime)
        or not isinstance(current_at, datetime)
        or prior_at.tzinfo is None
        or current_at.tzinfo is None
    ):
        return result
    seconds = (current_at - prior_at).total_seconds()
    if not 0.0 < seconds <= 100.0:
        return result
    prior = assess_foxess_ac_side_sample(previous)
    now = assess_foxess_ac_side_sample(current)
    if prior["status"] != "ac_cross_check_pass":
        return result
    if now["status"] != "ac_load_mismatch":
        result["status"] = "no_ac_disagreement"
        return result
    ac_previous = _number(prior.get("inverter_ac_kw"))
    ac_now = _number(now.get("inverter_ac_kw"))
    ct_previous = _number(prior.get("grid_ct_kw"))
    ct_now = _number(now.get("grid_ct_kw"))
    house_previous = _number(prior.get("foxess_reported_load_kw"))
    house_now = _number(now.get("foxess_reported_load_kw"))
    battery_previous = _number(getattr(previous, "battery_power_kw", None))
    battery_now = _number(getattr(current, "battery_power_kw", None))
    solar_previous = _number(getattr(previous, "solar_power_kw", None))
    solar_now = _number(getattr(current, "solar_power_kw", None))
    values = (
        ac_previous,
        ac_now,
        ct_previous,
        ct_now,
        house_previous,
        house_now,
        battery_previous,
        battery_now,
        solar_previous,
        solar_now,
    )
    if any(value is None for value in values):
        return result
    assert all(value is not None for value in values)
    if {"battery_power_kw", "solar_power_kw"} & (
        set(getattr(previous, "stale_fields", ()) or ())
        | set(getattr(current, "stale_fields", ()) or ())
    ):
        return result
    delta_ac = ac_now - ac_previous
    delta_ct = ct_now - ct_previous
    delta_house = house_now - house_previous
    delta_battery = battery_now - battery_previous
    delta_solar = solar_now - solar_previous
    result.update(
        {
            "seconds_between_samples": round(seconds, 1),
            "inverter_ac_change_kw": round(delta_ac, 3),
            "grid_ct_change_kw": round(delta_ct, 3),
            "reported_house_change_kw": round(delta_house, 3),
            "battery_dc_change_kw": round(delta_battery, 3),
            "solar_change_kw": round(delta_solar, 3),
            "ac_residual_after_kw": now["ac_load_residual_kw"],
            "status": "ac_disagreement_without_isolated_ct_step",
        }
    )
    if (
        ct_previous > 0.75
        and -0.25 <= ct_now <= 0.25
        and delta_ct < -0.75
        and abs(delta_ac) <= 0.2
        and abs(delta_house) <= 0.2
        and abs(delta_battery) <= 0.3
        and abs(delta_solar) <= 0.3
    ):
        result["status"] = "ct_export_step_without_matching_source_or_load_step"
    return result
