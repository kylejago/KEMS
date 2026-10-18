"""Read-only energy-session guard for unattended KEMS maintenance.

The updater never writes inverter or EV controls to make maintenance possible.
Unknown critical state is a reason to defer, not permission to restart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

EVENT_LEAD = timedelta(minutes=15)
EVENT_RECOVERY = timedelta(minutes=5)
MAX_SNAPSHOT_AGE = timedelta(minutes=2)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        return None
    return result.astimezone(UTC)


def _near_window(now: datetime, start: Any, end: Any) -> bool:
    begin = _datetime(start)
    finish = _datetime(end)
    if begin is None or finish is None or finish <= begin:
        return False
    instant = now.astimezone(UTC)
    return begin - EVENT_LEAD <= instant < finish + EVENT_RECOVERY


def _on(states: dict[str, str], key: str) -> bool:
    return states.get(key) == "on"


def maintenance_energy_blockers(
    *,
    now: datetime,
    snapshot: Any,
    happy_hour: dict[str, Any] | None,
    power_down: dict[str, Any] | None,
    foxess: dict[str, Any] | None,
    rolling_export: dict[str, Any] | None,
    states: dict[str, str],
) -> list[str]:
    """Decide if an *automatic* update/restart must wait.

    This is not a commissioning or permission function. It only prevents
    software maintenance interrupting an energy session. A manual update
    remains an explicit user-initiated action.
    """
    reasons: list[str] = []
    if now.tzinfo is None:
        return ["Maintenance clock is not timezone-aware"]
    timepoint = now.astimezone(UTC)
    if snapshot is None:
        return ["Live energy telemetry has not initialised"]
    last = _datetime(getattr(snapshot, "timestamp", None))
    if last is None or abs(timepoint - last) > MAX_SNAPSHOT_AGE:
        reasons.append("Live energy telemetry is not recent enough")

    happy = happy_hour if isinstance(happy_hour, dict) else {}
    if _near_window(timepoint, happy.get("start"), happy.get("end")):
        reasons.append("Booked Happy Hour active or within 15 minutes")

    pd = power_down if isinstance(power_down, dict) else {}
    if pd.get("active") is True or getattr(snapshot, "saving_session_active", False):
        reasons.append("Power Down session active")
    if _near_window(
        timepoint,
        states.get("next_power_down_start"),
        states.get("next_power_down_end"),
    ):
        reasons.append("Power Down session imminent or settling")

    if _on(states, "off_peak") or _on(states, "intelligent_slot"):
        reasons.append("Cheap or Intelligent Octopus charging window active")
    if getattr(snapshot, "cheap_period_confirmed", False):
        reasons.append("Confirmed cheap charging authority active")
    if _near_window(
        timepoint,
        states.get("next_off_peak_start"),
        states.get("off_peak_end"),
    ):
        reasons.append("Confirmed cheap window imminent or settling")
    # The next cheap-period end may refer to tomorrow; if no clear end
    # is known, still protect the 15 minutes before its start.
    upcoming = _datetime(states.get("next_off_peak_start"))
    if upcoming is not None and timedelta(0) <= upcoming - timepoint <= EVENT_LEAD:
        reasons.append("Cheap charging window begins within 15 minutes")

    if _on(states, "ev_charging") or (
        (_number(getattr(snapshot, "ev_power_kw", None)) or 0.0) > 0.15
    ):
        reasons.append("EV is charging")

    battery_kw = _number(getattr(snapshot, "battery_power_kw", None))
    export_kw = _number(getattr(snapshot, "grid_export_kw", None))
    if battery_kw is None or export_kw is None:
        reasons.append("Battery or grid export power not verified")
    else:
        if battery_kw < -0.25:
            reasons.append("Physical battery charging active")
        if battery_kw > 0.25 and export_kw > 0.2:
            reasons.append("Physical battery export active")

    fox = foxess if isinstance(foxess, dict) else {}
    if fox.get("commissioning_restore_pending") is True:
        reasons.append("FoxESS control restoration pending")
    action = str(fox.get("decision_action") or "").strip().lower()
    if action in {"force_charge", "force_discharge"}:
        reasons.append("FoxESS forced charging/export control active")
    if str(states.get("foxess_work_mode") or "").strip().lower() in {
        "force charge",
        "force discharge",
        "force_charge",
        "force_discharge",
    }:
        reasons.append("Inverter force-charge/discharge mode active")

    rolling = rolling_export if isinstance(rolling_export, dict) else {}
    if (_number(rolling.get("current_battery_export_target_kw")) or 0.0) > 0.15 and _on(
        states, "control_enabled"
    ):
        reasons.append("Physical Agile export requested")

    return reasons
