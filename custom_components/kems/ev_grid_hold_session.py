"""Restart-safe floor ownership for the bounded whole-bus EV cheap-grid hold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.ev_grid_guard import protect_live_cheap_ev

_MAX_RETAINED_AGE = timedelta(hours=12)


class EVGridHoldSession:
    """Do not chase a falling physical SoC down during one EV session."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.ev_grid_hold"
        )
        self._held_floor: float | None = None
        self._last_status = "inactive"

    @property
    def status(self) -> dict[str, Any]:
        return {
            "status": self._last_status,
            "latched_min_soc_percent": self._held_floor,
            "physical_isolation_proven": False,
            "new_hardware_write_scope": False,
        }

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        value = data.get("held_floor")
        saved_at = data.get("saved_at")
        try:
            timestamp = datetime.fromisoformat(str(saved_at))
            candidate = float(value)
        except (TypeError, ValueError):
            return
        if (
            timestamp.tzinfo is not None
            and timedelta(0)
            <= datetime.now(UTC) - timestamp.astimezone(UTC)
            <= _MAX_RETAINED_AGE
            and isfinite(candidate)
            and 0.0 <= candidate <= 100.0
        ):
            self._held_floor = candidate

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "held_floor": self._held_floor,
                "saved_at": datetime.now(UTC).isoformat(),
            }
        )

    async def async_apply(
        self,
        snapshot: Any,
        control: Any,
        config: Any,
        *,
        no_paid_export_mode: bool,
    ) -> Any:
        """Apply reviewed guard and persist the floor before hardware output."""
        power = snapshot.ev_power_kw
        stopped = bool(
            snapshot.ev_charging is False
            and power is not None
            and isfinite(power)
            and power <= 0.25
            and snapshot.ev_power_age_seconds is not None
            and snapshot.ev_power_age_seconds <= 90
        )
        if (
            not snapshot.cheap_period_confirmed
            or not no_paid_export_mode
            or stopped
        ) and self._held_floor is not None:
            self._held_floor = None
            await self.async_save()

        guarded = protect_live_cheap_ev(
            snapshot,
            control,
            config,
            no_paid_export_mode=no_paid_export_mode,
            held_floor_percent=self._held_floor,
        )
        self._last_status = guarded.ev_grid_guard_status
        if guarded.ev_grid_guard_status in {
            "ev_battery_hold",
            "ev_battery_hold_conservative_scope",
            "ev_battery_hold_with_cheap_charge",
            "ev_battery_hold_with_cheap_charge_conservative_scope",
            "battery_hold_ev_or_site_unverified",
            "observed_site_import_limit_exceeded",
        }:
            floor = guarded.desired_min_soc_percent
            if isfinite(floor) and (
                self._held_floor is None or floor > self._held_floor
            ):
                self._held_floor = floor
                await self.async_save()
        return guarded
