"""Opt-in, physically read-back-gated Ohme pause for low-SOC house Self Use.

The whole-house FoxESS Min SoC is not circuit-specific. A plugged-in EV
cannot share a 10% household floor unless its charger has been paused and
verified; 0 kW alone is not sufficient. This feature is separately opt-in
because it adds an Ohme actuator outside the existing Happy Hour authority.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from homeassistant.helpers.storage import Store

from .const import CONF_OHME_IDLE_HOUSE_BRIDGE_ENABLED, DOMAIN, STORAGE_NAMESPACE

_MODE_ENTITY = "select.ohme_epod_charge_mode"
_STATUS_ENTITY = "sensor.ohme_epod_status"
_REQUIRED_OPTIONS = {"smart charge", "max charge", "paused"}
_MAX_AGE_SECONDS = 120
_MIN_DISTINCT_PROOF_SECONDS = 20
# Pre-arm the opt-in charger pause before reaching the 15% export reserve.
# Never lower the physical floor until separately verified near reserve.
_EARLY_PAUSE_MARGIN_PERCENT = 3.5


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def _fresh(state: Any, *, now: datetime) -> bool:
    if state is None:
        return False
    reported = getattr(state, "last_reported", None)
    return bool(
        isinstance(reported, datetime)
        and reported.tzinfo is not None
        and 0 <= (now - reported).total_seconds() <= _MAX_AGE_SECONDS
    )


def _real_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def household_bridge_eligible(
    *,
    opted_in: bool,
    control_authorised: bool,
    paid_agile_selected: bool,
    cheap_period: bool,
    active_session: bool,
    ev_connected: bool | None,
    ev_charging: bool | None,
    ev_power_kw: float | None,
    ev_power_age_seconds: float | None,
    battery_soc: float | None,
    desired_export_kw: float | None,
    normal_reserve_percent: float | None,
    owned_paused_at_floor: bool = False,
) -> bool:
    """Never lower the bus floor on a merely idle, unisolated charger."""
    ev_kw = _real_number(ev_power_kw)
    age = _real_number(ev_power_age_seconds)
    soc = _real_number(battery_soc)
    export = _real_number(desired_export_kw)
    reserve = _real_number(normal_reserve_percent)
    return bool(
        opted_in
        and control_authorised
        and paid_agile_selected
        and not cheap_period
        and not active_session
        and ev_connected is True
        and ev_charging is False
        and ev_kw is not None
        and 0 <= ev_kw <= 0.05
        and age is not None
        and 0 <= age <= 60
        and soc is not None
        and reserve is not None
        # A new bridge must pre-arm above 10%.  Once KEMS already owns the
        # pause, allow the exact 10% boundary so we do not restore 15% and
        # trigger expensive automatic FoxESS reserve replenishment.
        # This flag alone is NOT proof: async_prepare still requires fresh,
        # independent post-pause mode and zero-power observations each scan.
        and (
            10.0 < soc <= reserve + _EARLY_PAUSE_MARGIN_PERCENT
            or (owned_paused_at_floor and soc == 10.0)
        )
        and abs(reserve - 15.0) <= 0.05
        and export is not None
        and export <= 0.001
    )


class OhmeIdleHouseholdBridge:
    """Pause the confirmed ePod before authorising the 10% house-only floor."""

    def __init__(self, hass: Any, entry: Any) -> None:
        self._hass = hass
        self._entry = entry
        self._store = Store(
            hass,
            1,
            f"{DOMAIN}.{entry.entry_id}.{STORAGE_NAMESPACE}.ohme_idle_house_bridge",
        )
        self._owned = False
        self._previous_mode: str | None = None
        self._first_paused_at: datetime | None = None
        self._first_power_report_at: datetime | None = None
        self._pause_requested_at: datetime | None = None
        self._last_result = "Not requested"
        self._status: dict[str, Any] = {}

    @property
    def owned(self) -> bool:
        """Whether this bridge owns the charger pause (not physical proof)."""
        return self._owned

    @property
    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(
                self._entry.options.get(CONF_OHME_IDLE_HOUSE_BRIDGE_ENABLED, False)
            ),
            "owned": self._owned,
            "previous_mode": self._previous_mode,
            "last_result": self._last_result,
            **self._status,
        }

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self._owned = bool(data.get("owned"))
            previous = data.get("previous_mode")
            self._previous_mode = (
                str(previous)
                if _normalise(previous) in {"smart charge", "paused"}
                else None
            )
        # A restart never inherits proof of a paused charger.
        self._first_paused_at = None
        self._first_power_report_at = None
        self._pause_requested_at = None

    async def _save(self) -> None:
        await self._store.async_save(
            {"owned": self._owned, "previous_mode": self._previous_mode}
        )

    def _valid_mode_state(self, now: datetime) -> Any:
        state = self._hass.states.get(_MODE_ENTITY)
        if not _fresh(state, now=now):
            return None
        options = {_normalise(v) for v in (state.attributes.get("options") or [])}
        if not _REQUIRED_OPTIONS.issubset(options):
            return None
        return state if _normalise(state.state) in _REQUIRED_OPTIONS else None

    async def _set_mode(self, mode: str, state: Any) -> bool:
        option = next(
            (
                str(value)
                for value in state.attributes.get("options", [])
                if _normalise(value) == _normalise(mode)
            ),
            None,
        )
        if option is None:
            self._last_result = "Ohme target mode is not available"
            return False
        try:
            async with asyncio.timeout(15):
                await self._hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": _MODE_ENTITY, "option": option},
                    blocking=True,
                )
        except Exception as err:
            self._last_result = f"Ohme mode command failed: {err}"
            return False
        self._last_result = f"Ohme {option} requested; physical readback required"
        return True

    async def async_prepare(
        self,
        *,
        snapshot: Any,
        eligible: bool,
        ev_status_entity: str | None,
        ev_power_entity: str | None,
        now: datetime | None = None,
    ) -> bool:
        """Return true only after TWO distinct fresh zero-power pause observations."""
        now = now or datetime.now(UTC)
        self._status = {"eligible": eligible, "pause_verified": False}
        if not eligible:
            self._first_paused_at = None
            self._first_power_report_at = None
            self._last_result = "Household bridge not authorised this scan"
            return False

        if ev_status_entity != _STATUS_ENTITY or not ev_power_entity:
            self._last_result = "Unreviewed Ohme source binding"
            return False
        ev_status = self._hass.states.get(ev_status_entity)
        ev_power = self._hass.states.get(ev_power_entity)
        if (
            not _fresh(ev_status, now=now)
            or _normalise(ev_status.state) not in {"plugged in", "paused", "finished"}
            or not _fresh(ev_power, now=now)
        ):
            self._first_paused_at = None
            self._first_power_report_at = None
            self._last_result = "Charger status or power readback is stale"
            return False
        observed_power = _real_number(ev_power.state)
        if observed_power is None or not 0.0 <= observed_power <= 0.05:
            self._first_paused_at = None
            self._first_power_report_at = None
            self._last_result = "Ohme power readback invalid or nonzero"
            return False
        mode_state = self._valid_mode_state(now)
        if mode_state is None:
            self._first_paused_at = None
            self._first_power_report_at = None
            self._last_result = "No fresh, uniquely reviewed ePod mode select"
            return False
        current_mode = _normalise(mode_state.state)
        if current_mode != "paused":
            self._first_paused_at = None
            self._first_power_report_at = None
            if self._owned:
                self._last_result = "Ohme mode changed externally; floor must rise"
                return False
            if current_mode != "smart charge":
                self._last_result = "Ohme Max charge is not safe to interrupt"
                return False
            # Persist ownership BEFORE sending any command: restart must never
            # forget a pause that the charger may have accepted.
            self._previous_mode = mode_state.state
            self._owned = True
            await self._save()
            self._pause_requested_at = now
            await self._set_mode("paused", mode_state)
            return False

        if not self._owned:
            self._last_result = "Externally Paused mode is not KEMS-owned"
            return False
        report = getattr(ev_power, "last_reported", None)
        mode_report = getattr(mode_state, "last_reported", None)
        if self._pause_requested_at is not None and (
            report <= self._pause_requested_at
            or mode_report <= self._pause_requested_at
        ):
            self._last_result = "Awaiting post-pause mode and power readback"
            return False
        if self._first_paused_at is None or self._first_power_report_at is None:
            self._first_paused_at = now
            self._first_power_report_at = report
            self._last_result = "First paused/zero-power observation"
            return False
        if (
            report == self._first_power_report_at
            or (now - self._first_paused_at).total_seconds()
            < _MIN_DISTINCT_PROOF_SECONDS
        ):
            self._last_result = "Awaiting distinct paused/zero-power observation"
            return False
        self._status["pause_verified"] = True
        self._last_result = "Two fresh paused/zero-power observations verified"
        return True

    async def async_restore_if_safe(
        self,
        *,
        keep_paused: bool,
        min_soc_entity: str | None,
        battery_soc: float | None,
        now: datetime | None = None,
    ) -> None:
        """Never unpause KEMS-owned Ohme while the physical floor is below SOC."""
        if not self._owned or keep_paused:
            return
        now = now or datetime.now(UTC)
        mode = self._valid_mode_state(now)
        floor_state = self._hass.states.get(min_soc_entity) if min_soc_entity else None
        floor = _real_number(floor_state.state if floor_state else None)
        soc = _real_number(battery_soc)
        if (
            mode is None
            or floor_state is None
            or floor is None
            or soc is None
            or floor < 15.0 - 0.05
            or floor + 0.05 < soc
            or not _fresh(floor_state, now=now)
        ):
            self._last_result = (
                "Ohme remains paused: restored physical MinSOC not yet proven"
            )
            return
        if _normalise(mode.state) == "paused":
            if not await self._set_mode(self._previous_mode or "smart charge", mode):
                return
            observed = self._valid_mode_state(now)
            if observed is None or _normalise(observed.state) == "paused":
                self._last_result = "Ohme resume requested; readback pending"
                return
        # Do not overwrite a manual user mode change, and only clear
        # ownership after physical FoxESS protection has been verified.
        self._owned = False
        self._previous_mode = None
        self._first_paused_at = None
        self._first_power_report_at = None
        self._pause_requested_at = None
        self._last_result = "Ohme bridge released after physical floor proof"
        await self._save()
