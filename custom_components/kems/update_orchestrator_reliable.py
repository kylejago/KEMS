"""Reliability repairs layered over the proven KEMS update orchestrator."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .dashboard import _combined_master_dashboard_bytes
from . import update_orchestrator as base


class ReliableKEMSUpdateOrchestrator(base.KEMSUpdateOrchestrator):
    """Keep coordinated updates restart-safe and verification-accurate."""

    async def async_set_policy(self, **changes: Any) -> None:
        """Re-arm a corrected failed transaction when automatic updates are enabled."""
        if (
            changes.get("automatic_updates") is True
            and self.pending
            and self.pending.get("stage") == "failed"
        ):
            self.pending.pop("error", None)
            self.last_error = None
            disruptive = bool(
                self.pending.get("maintenance", {}).get("required", True)
            )
            self.pending["stage"] = "scheduled" if disruptive else "ready"
            self.pending["scheduled_for"] = (
                self._scheduled_time().isoformat() if disruptive else None
            )
            self.maintenance = self._maintenance_payload(
                "scheduled" if disruptive else "update_available",
                self.pending,
            )
        await super().async_set_policy(**changes)

    async def _consider_bundle(self, bundle: dict[str, Any]) -> None:
        """Always pass HACS the canonical bundle target, never a leading-v alias."""
        target = base._component_target(bundle, "kems_core")
        release = dict(bundle.get("release") or {})
        if target and release:
            release["tag"] = target
            bundle = {**bundle, "release": release}
        await super()._consider_bundle(bundle)

    async def async_verify_pending(self, *, save: bool = True) -> None:
        """Do not claim success until the post-restart bundle is loaded again."""
        if self.pending and self.latest_bundle is None:
            if save:
                await self._async_save()
            self._write_legacy_states()
            return
        await super().async_verify_pending(save=save)

    def _dashboard_current(self) -> bool | None:
        """Verify the installed dashboard against the actual combined managed file."""
        installed = self.hass.config.path(base.MANAGED_DASHBOARD_FILENAME) if hasattr(base, "MANAGED_DASHBOARD_FILENAME") else self.hass.config.path("kems_master_dashboard.yaml")
        try:
            from pathlib import Path

            return Path(installed).read_bytes() == _combined_master_dashboard_bytes()
        except (OSError, ValueError):
            return None

    def _maintenance_payload(
        self, status: str, pending: dict[str, Any]
    ) -> dict[str, Any]:
        """Only expose an error while maintenance is actually failed."""
        payload = super()._maintenance_payload(status, pending)
        if status != "failed":
            payload["error"] = None
        return payload


async def async_setup_update_orchestrator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ReliableKEMSUpdateOrchestrator:
    """Set up the reliable orchestrator while preserving the existing public API."""
    orchestrator = ReliableKEMSUpdateOrchestrator(hass, entry)
    hass.data.setdefault(base.DATA_KEY, {})[entry.entry_id] = orchestrator
    await orchestrator.async_start()

    if not hass.services.has_service(DOMAIN, base.SERVICE_CHECK_UPDATES):

        async def check_updates(_call: ServiceCall) -> None:
            current = base._first_orchestrator(hass)
            if current is not None:
                await current.async_check(force=True)

        async def apply_update(call: ServiceCall) -> None:
            current = base._first_orchestrator(hass)
            if current is not None:
                await current.async_apply_pending(
                    force=bool(call.data.get("force", False))
                )

        async def cancel_update(_call: ServiceCall) -> None:
            current = base._first_orchestrator(hass)
            if current is not None:
                await current.async_cancel()

        hass.services.async_register(
            DOMAIN,
            base.SERVICE_CHECK_UPDATES,
            check_updates,
        )
        hass.services.async_register(
            DOMAIN,
            base.SERVICE_APPLY_UPDATE,
            apply_update,
        )
        hass.services.async_register(
            DOMAIN,
            base.SERVICE_CANCEL_UPDATE,
            cancel_update,
        )
    return orchestrator
