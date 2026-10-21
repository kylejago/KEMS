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
