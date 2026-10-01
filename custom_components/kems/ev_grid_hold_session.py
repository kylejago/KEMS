"""Restart-safe floor ownership for the bounded whole-bus EV cheap-grid hold."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.ev_grid_guard import (
    protect_live_cheap_ev,
    protect_pending_intelligent_ev_hold,
)

_MAX_RETAINED_AGE = timedelta(hours=12)


class EVGridHoldSession:
    """Do not chase a falling physical SoC down during one EV session."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.ev_grid_hold"
        )
        self._held_floor: float | None = None
        self._last_confirmed_cheap_at: datetime | None = None
        self._grace_active = False
        self._pending_intelligent_hold_active = False
        self._last_status = "inactive"

    @property
    def status(self) -> dict[str, Any]:
        return {
            "status": self._last_status,
            "latched_min_soc_percent": self._held_floor,
            "source_uncertainty_grace_active": self._grace_active,
            "pending_intelligent_ev_hold_active": (
                self._pending_intelligent_hold_active
            ),
            "last_confirmed_cheap_at": (
                self._last_confirmed_cheap_at.isoformat()
                if self._last_confirmed_cheap_at is not None
                else None
            ),
            "physical_isolation_proven": False,
            "new_hardware_write_scope": False,
        }

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        value = data.get("held_floor")
        saved_at = data.get("saved_at")
        last_confirmed = data.get("last_confirmed_cheap_at")
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
        try:
            confirmed_at = datetime.fromisoformat(str(last_confirmed))
        except (TypeError, ValueError):
            confirmed_at = None
        if (
            confirmed_at is not None
            and confirmed_at.tzinfo is not None
            and timedelta(0)
            <= datetime.now(UTC) - confirmed_at.astimezone(UTC)
            <= _MAX_RETAINED_AGE
        ):
            self._last_confirmed_cheap_at = confirmed_at

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "held_floor": self._held_floor,
                "last_confirmed_cheap_at": (
                    self._last_confirmed_cheap_at.isoformat()
                    if self._last_confirmed_cheap_at is not None
                    else None
                ),
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
        source_uncertain: bool = False,
        source_grace_seconds: int = 90,
    ) -> Any:
        """Apply reviewed guard and preserve only a bounded uncertain-source hold."""
        now = snapshot.timestamp
        disconnected = snapshot.ev_connected is False

        pending = protect_pending_intelligent_ev_hold(
            snapshot,
            control,
            config,
            no_paid_export_mode=no_paid_export_mode,
            held_floor_percent=self._held_floor,
        )
        self._pending_intelligent_hold_active = (
            pending.ev_grid_guard_status
            == "ev_battery_hold_pending_intelligent_window"
        )
        if self._pending_intelligent_hold_active:
            self._grace_active = False
            self._last_status = pending.ev_grid_guard_status
            floor = pending.desired_min_soc_percent
            if isfinite(floor) and (
                self._held_floor is None or floor > self._held_floor
            ):
                self._held_floor = floor
                await self.async_save()
            return pending

        if snapshot.cheap_period_confirmed:
            self._last_confirmed_cheap_at = now
            self._grace_active = False
        else:
            grace = timedelta(seconds=max(int(source_grace_seconds), 0))
            self._grace_active = bool(
                self._held_floor is not None
                and self._last_confirmed_cheap_at is not None
                and source_uncertain
                and not disconnected
                and no_paid_export_mode
                and timedelta(0) <= now - self._last_confirmed_cheap_at <= grace
            )

        if (
            (not snapshot.cheap_period_confirmed and not self._grace_active)
            or not no_paid_export_mode
            or disconnected
        ) and self._held_floor is not None:
            self._held_floor = None
            self._last_confirmed_cheap_at = None
            self._grace_active = False
            self._pending_intelligent_hold_active = False
            await self.async_save()

        if self._grace_active:
            self._last_status = "ev_battery_hold_source_grace"
            return replace(
                control,
                ev_grid_guard_status="ev_battery_hold_source_grace",
            )

        guarded = protect_live_cheap_ev(
            snapshot,
            control,
            config,
            no_paid_export_mode=no_paid_export_mode,
            held_floor_percent=self._held_floor,
        )
        self._last_status = guarded.ev_grid_guard_status
        if guarded.ev_grid_guard_status in {
            "ev_battery_hold_prearmed",
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
                if snapshot.cheap_period_confirmed:
                    self._last_confirmed_cheap_at = now
                await self.async_save()
        return guarded
