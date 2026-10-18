"""Narrow opt-in Ohme control for an automatically verified Happy Hour.

This is deliberately not general EV control. KEMS may temporarily select
Ohme ``Max charge`` only while an automatic/retained Octopus Happy Hour has
active per-reward-hour import authority. When that authority ends KEMS
restores the mode it observed before taking ownership. FoxESS writes remain
completely separate and blocked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED,
    DOMAIN,
    STORAGE_NAMESPACE,
)

STORAGE_VERSION = 1
MAX_SAFE_SCAN_SECONDS = 120
ASSUMED_OHME_MAX_CHARGE_KW = 7.4
_EXPECTED_MODES = {"smart charge", "max charge", "paused"}
_CONFIRMED_CHARGE_MODE_ENTITY = "select.ohme_epod_charge_mode"
_HAPPY_HOUR_SENSOR = "sensor.kems_agile_happy_hour_plan"


def _number(value: Any) -> float | None:
    import math

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _normalise(value: Any) -> str:
    """Compare Ohme's smart_charge or Smart charge as the same mode.

    Keep the original HA select option unchanged for service calls.
    """
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def ohme_happy_hour_write_decision(
    *,
    enabled: bool,
    automatic_source: bool,
    authority_active: bool,
    ledger_complete: bool,
    ev_connected: bool,
    data_fresh: bool,
    plan_safe: bool,
    grid_available: bool,
    island_mode_active: bool,
    power_down_active: bool,
    emergency_stop: bool,
    scan_interval_seconds: int,
    reward_remaining_kwh: float,
    ev_allowance_kwh: float,
    projected_home_grid_kw: float,
    battery_charge_target_kw: float,
) -> tuple[bool, str, float]:
    """Return whether KEMS may force Ohme Max charge this scan."""
    if not enabled:
        return False, "Ohme Happy Hour control disabled", 0.0
    if not automatic_source:
        return False, "Happy Hour is not automatically verified by Octopus", 0.0
    if emergency_stop:
        return False, "KEMS emergency stop is active", 0.0
    if power_down_active:
        return False, "Power Down has priority", 0.0
    if not authority_active:
        return False, "Happy Hour import authority is not active", 0.0
    if not ledger_complete:
        return False, "Reward-hour import ledger is incomplete", 0.0
    if not ev_connected:
        return False, "EV is not connected", 0.0
    if not data_fresh or not plan_safe or not grid_available or island_mode_active:
        return False, "Control safety envelope is not healthy", 0.0
    if scan_interval_seconds > MAX_SAFE_SCAN_SECONDS:
        return False, "KEMS scan interval is too slow for a hard 16 kWh cap", 0.0

    expected_site_kw = (
        max(projected_home_grid_kw, 0.0)
        + max(battery_charge_target_kw, 0.0)
        + ASSUMED_OHME_MAX_CHARGE_KW
    )
    guard_kwh = expected_site_kw * max(scan_interval_seconds, 1) / 3600.0 + 0.05
    ev_guard_kwh = (
        ASSUMED_OHME_MAX_CHARGE_KW * max(scan_interval_seconds, 1) / 3600.0 + 0.05
    )
    if reward_remaining_kwh <= guard_kwh:
        return False, "Reward-hour cap guard reached", round(guard_kwh, 3)
    if ev_allowance_kwh <= ev_guard_kwh:
        return (
            False,
            "No safe EV allowance remains after battery/home reserve",
            round(guard_kwh, 3),
        )
    return True, "Automatic Happy Hour EV allowance available", round(guard_kwh, 3)


def _automatic_happy_hour_source(happy_hour: dict[str, Any]) -> bool:
    """Accept live joined events or KEMS-confirmed reward bookings only."""
    status = str(happy_hour.get("automatic_status") or "")
    confirmed_kems_booking = bool(
        happy_hour.get("booking_authoritative") is True
        and happy_hour.get("booking_source") == "kems_auto_join"
        and status in ("detected_kems_booking", "retained_active")
    )
    return bool(
        happy_hour.get("source") == "octopus_energy"
        and (status.endswith("active") or confirmed_kems_booking)
    )


class OhmeHappyHourController:
    """Own only the temporary Ohme mode change KEMS itself initiated."""

    def __init__(self, hass: Any, entry: Any, *, ev_status_entity: str | None) -> None:
        self._hass = hass
        self._entry = entry
        self._ev_status_entity = ev_status_entity
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.{STORAGE_NAMESPACE}.happy_hour_ohme",
        )
        self._owned = False
        self._previous_mode: str | None = None
        self._event_start: str | None = None
        self._last_command: str | None = None
        self._last_result = "Never commanded"
        self._last_command_at: str | None = None
        self._restore_attempts = 0
        self._status: dict[str, Any] = {}

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self._owned = bool(data.get("owned"))
            self._previous_mode = data.get("previous_mode")
            self._event_start = data.get("event_start")

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "owned": self._owned,
                "previous_mode": self._previous_mode,
                "event_start": self._event_start,
            }
        )

    def _charge_mode_entity(self) -> str | None:
        # The user-confirmed ePod selector is authoritative for this charger.
        # Require the actual live option set: the select may be unavailable
        # while unplugged, and its existence alone never authorises a write.
        if self._ev_status_entity == "sensor.ohme_epod_status":
            confirmed = self._hass.states.get(_CONFIRMED_CHARGE_MODE_ENTITY)
            if confirmed is not None:
                options = {
                    _normalise(option)
                    for option in (confirmed.attributes.get("options") or [])
                }
                if (
                    _EXPECTED_MODES.issubset(options)
                    and _normalise(confirmed.state) in _EXPECTED_MODES
                ):
                    return _CONFIRMED_CHARGE_MODE_ENTITY
        registry = er.async_get(self._hass)
        device_id = None
        if self._ev_status_entity:
            status_entry = registry.async_get(self._ev_status_entity)
            device_id = status_entry.device_id if status_entry else None

        candidates: list[str] = []
        for entry in registry.entities.values():
            if entry.platform != "ohme" or not entry.entity_id.startswith("select."):
                continue
            if device_id is not None and entry.device_id != device_id:
                continue
            state = self._hass.states.get(entry.entity_id)
            options = {
                _normalise(item)
                for item in ((state.attributes.get("options") if state else None) or [])
            }
            text = _normalise(
                " ".join(
                    (
                        entry.entity_id,
                        str(entry.original_name or ""),
                        str(state.attributes.get("friendly_name", "") if state else ""),
                    )
                )
            )
            if (
                _EXPECTED_MODES.issubset(options)
                and state is not None
                and _normalise(state.state) in _EXPECTED_MODES
                and "charge" in text
                and "mode" in text
            ):
                candidates.append(entry.entity_id)
        if len(candidates) == 1:
            return candidates[0]

        if device_id is not None:
            return None
        return candidates[0] if len(candidates) == 1 else None

    def _exact_option(self, entity_id: str, requested: str) -> str | None:
        state = self._hass.states.get(entity_id)
        if state is None:
            return None
        for option in state.attributes.get("options", []) or []:
            if _normalise(option) == _normalise(requested):
                return str(option)
        return None

    async def _async_set_mode(self, entity_id: str, requested: str) -> bool:
        option = self._exact_option(entity_id, requested)
        if option is None:
            self._last_result = f"Ohme option unavailable: {requested}"
            return False
        try:
            async with asyncio.timeout(15):
                await self._hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": entity_id, "option": option},
                    blocking=True,
                )
        except Exception as err:  # Home Assistant service/network boundary
            self._last_result = f"Ohme write failed: {err}"
            return False

        self._last_command = option
        self._last_command_at = datetime.now(UTC).isoformat()
        observed = self._hass.states.get(entity_id)
        if observed is not None and _normalise(observed.state) == _normalise(option):
            self._last_result = f"Confirmed {option}"
        else:
            self._last_result = f"Requested {option}; readback pending"
        return True

    async def _async_restore(self, entity_id: str | None) -> None:
        if not self._owned:
            return
        if entity_id is None:
            self._last_result = (
                "Cannot restore Ohme mode: charge-mode entity unavailable"
            )
            return
        state = self._hass.states.get(entity_id)
        current = _normalise(state.state if state else None)
        target = self._previous_mode or "Smart charge"
        if current not in _EXPECTED_MODES:
            self._last_result = (
                "Ohme restoration deferred until a valid charge mode returns"
            )
            return
        if _normalise(target) == "max charge":
            target = "Smart charge"
        if current in _EXPECTED_MODES and current != "max charge":
            self._owned = False
            self._restore_attempts = 0
            await self._async_save()
            return
        if self._restore_attempts >= 3:
            self._last_result = f"Restore failed after 3 attempts; target was {target}"
            return
        self._restore_attempts += 1
        if await self._async_set_mode(entity_id, target):
            observed = self._hass.states.get(entity_id)
            if observed is not None and _normalise(observed.state) == _normalise(
                target
            ):
                self._owned = False
                self._restore_attempts = 0
                await self._async_save()

    def _publish(self, payload: dict[str, Any]) -> None:
        """Retain audit state for diagnostics without mutating HA entities."""
        self._status = dict(payload)

    async def async_update(
        self,
        *,
        snapshot: Any,
        control: Any,
        happy_hour: dict[str, Any],
        power_down: dict[str, Any],
        scan_interval_seconds: int,
        emergency_stop: bool,
        foxess_control: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enabled = bool(
            self._entry.options.get(
                CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED,
                False,
            )
        )
        entity_id = self._charge_mode_entity()
        state = self._hass.states.get(entity_id) if entity_id else None
        observed_mode = state.state if state is not None else None
        automatic_source = _automatic_happy_hour_source(happy_hour)
        allow, reason, guard_kwh = ohme_happy_hour_write_decision(
            enabled=enabled,
            automatic_source=automatic_source,
            authority_active=bool(happy_hour.get("happy_hour_import_authority_active")),
            ledger_complete=bool(happy_hour.get("current_reward_hour_ledger_complete")),
            ev_connected=bool(getattr(snapshot, "ev_connected", False)),
            data_fresh=bool(getattr(control, "data_fresh", False)),
            plan_safe=bool(getattr(control, "plan_safe", False)),
            grid_available=bool(getattr(control, "grid_available", False)),
            island_mode_active=bool(getattr(control, "island_mode_active", False)),
            power_down_active=bool(power_down.get("active")),
            emergency_stop=emergency_stop,
            scan_interval_seconds=int(scan_interval_seconds),
            reward_remaining_kwh=float(
                happy_hour.get("current_reward_hour_remaining_kwh") or 0.0
            ),
            ev_allowance_kwh=float(happy_hour.get("ev_allowance_kwh_remaining") or 0.0),
            projected_home_grid_kw=float(
                happy_hour.get("projected_non_ev_home_grid_kw") or 0.0
            ),
            battery_charge_target_kw=float(happy_hour.get("charge_target_kw") or 0.0),
        )

        # Happy Hour EV charging is *additional site demand*, never an
        # independent permission. A generic Control plan and a reward ledger
        # cannot override absent battery protection or a rejected FoxESS write.
        foxess = foxess_control if isinstance(foxess_control, dict) else {}
        battery_kw = _number(getattr(snapshot, "battery_power_kw", None))
        ages = getattr(snapshot, "source_age_seconds", None)
        ages = ages if isinstance(ages, dict) else {}
        battery_age = _number(ages.get("battery_power_kw"))
        battery_currently_safe = bool(
            battery_kw is not None
            and battery_kw <= 0.15
            and battery_age is not None
            and 0.0 <= battery_age <= 30.0
            and "battery_power_kw"
            not in (getattr(snapshot, "stale_fields", ()) or ())
        )
        verified_grid_charge = bool(
            foxess.get("happy_hour_charge_authorised") is True
            and foxess.get("commands_permitted") is True
            and foxess.get("decision_action") == "force_charge"
            and foxess.get("last_applied_action") == "force_charge"
        )
        if allow and not bool(getattr(control, "desired_ev_charging_allowed", False)):
            allow = False
            reason = "Main Happy Hour control has not authorised EV charging"
        if allow and not verified_grid_charge:
            allow = False
            reason = "FoxESS grid-charging mode is not verified active"
        if allow and not battery_currently_safe:
            allow = False
            reason = "Battery is discharging or live battery power is unverified"

        if allow and entity_id is not None:
            if _normalise(observed_mode) == "max charge":
                if self._owned:
                    reason = "KEMS-owned Ohme Max charge active"
                else:
                    reason = "Ohme already in Max charge; KEMS did not take ownership"
            else:
                if not self._owned:
                    if _normalise(observed_mode) not in _EXPECTED_MODES:
                        allow = False
                        reason = "Unverified prior Ohme mode; Max charge blocked"
                    else:
                        self._previous_mode = observed_mode
                        self._event_start = str(happy_hour.get("start") or "")
                if allow and await self._async_set_mode(entity_id, "Max charge"):
                    self._owned = True
                    self._restore_attempts = 0
                    await self._async_save()
        elif self._owned:
            await self._async_restore(entity_id)

        payload = {
            "enabled": enabled,
            "entity_id": entity_id,
            "observed_mode": observed_mode,
            "owned_by_kems": self._owned,
            "previous_mode": self._previous_mode,
            "automatic_source_eligible": automatic_source,
            "max_charge_allowed_this_scan": allow,
            "reason": reason,
            "reward_cap_guard_kwh": guard_kwh,
            "last_command": self._last_command,
            "last_result": self._last_result,
            "last_command_at": self._last_command_at,
            "status": (
                "Max charge active"
                if self._owned and allow
                else "Restoring normal mode" if self._owned else reason
            ),
        }
        self._publish(payload)
        return payload

    async def async_shutdown(self) -> None:
        if self._owned:
            await self._async_restore(self._charge_mode_entity())
