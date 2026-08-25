"""Strict managed-dashboard convergence for coordinated KEMS updates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from . import update_orchestrator as base
from . import update_orchestrator_reliable as reliable
from .const import DOMAIN
from .dashboard import _combined_master_dashboard_bytes
from .dashboard_convergence import (
    DashboardConvergenceError,
    DashboardVerification,
    sync_and_verify_managed_dashboard,
    verify_managed_dashboard,
)

_UPDATE_VIEW = "\n  - title: Updates\n    path: updates\n"
_UPDATE_CARDS = "    cards:\n"
_UPDATE_BUTTON = (
    "      - type: button\n"
    "        name: Check for updates\n"
    "        icon: mdi:refresh\n"
    "        show_state: false\n"
    "        tap_action:\n"
    "          action: perform-action\n"
    "          perform_action: kems.check_for_updates\n"
)


def _managed_dashboard_bytes() -> bytes:
    """Build one deterministic managed dashboard payload for write and verify."""
    content = _combined_master_dashboard_bytes().decode("utf-8")
    if _UPDATE_BUTTON in content:
        return content.encode()

    view_start = content.find(_UPDATE_VIEW)
    if view_start < 0:
        raise ValueError("Managed KEMS Updates view is missing")
    next_view = content.find("\n  - title:", view_start + len(_UPDATE_VIEW))
    cards_at = content.find(_UPDATE_CARDS, view_start)
    if cards_at < 0 or (next_view >= 0 and cards_at >= next_view):
        raise ValueError("Managed KEMS Updates view has no cards section")
    insert_at = cards_at + len(_UPDATE_CARDS)
    return (content[:insert_at] + _UPDATE_BUTTON + content[insert_at:]).encode()


async def _async_converge_dashboard(
    hass: HomeAssistant,
    *,
    strict: bool,
) -> DashboardVerification | None:
    """Repair and verify the managed dashboard with optional strict failure."""
    target = Path(hass.config.path("kems_master_dashboard.yaml"))
    try:
        expected = await hass.async_add_executor_job(_managed_dashboard_bytes)
        return await hass.async_add_executor_job(
            sync_and_verify_managed_dashboard,
            target,
            expected,
        )
    except (OSError, ValueError, DashboardConvergenceError) as error:
        message = f"Managed dashboard convergence failed at {target}: {error}"
        if strict:
            raise HomeAssistantError(message) from error
        base.LOGGER.exception(message)
        return None


class ConvergentKEMSUpdateOrchestrator(reliable.ReliableKEMSUpdateOrchestrator):
    """Require the managed dashboard to converge before update success is possible."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._dashboard_verification_detail: str | None = None
        self._dashboard_expected_sha256: str | None = None
        self._dashboard_installed_sha256: str | None = None

    def _remember_dashboard_verification(
        self,
        verification: DashboardVerification,
    ) -> None:
        self._dashboard_verification_detail = verification.detail
        self._dashboard_expected_sha256 = verification.expected_sha256
        self._dashboard_installed_sha256 = verification.installed_sha256

    async def async_verify_pending(self, *, save: bool = True) -> None:
        """Converge the dashboard only after the pending target core is active."""
        if self.pending and self.latest_bundle is None:
            if save:
                await self._async_save()
            self._write_legacy_states()
            return

        if self.pending:
            target = str(self.pending.get("target") or "").strip()
            running = base._installed_integration_version()
            if target and not base._version_matches(running, target):
                relation = base.version_relation(target, running)
                if relation is not None and relation < 0:
                    await base.KEMSUpdateOrchestrator.async_verify_pending(
                        self, save=save
                    )
                    return
                self._dashboard_verification_detail = (
                    f"Waiting for KEMS core {target}; running {running}. "
                    "Dashboard convergence starts only after the target core is active."
                )
                self._dashboard_expected_sha256 = None
                self._dashboard_installed_sha256 = None
                if save:
                    await self._async_save()
                self._write_legacy_states()
                return

            try:
                verification = await _async_converge_dashboard(self.hass, strict=True)
            except HomeAssistantError as error:
                self._dashboard_verification_detail = str(error)
                await self._fail_pending(str(error))
                return
            if verification is None:
                await self._fail_pending(
                    "Managed dashboard convergence returned no verification result"
                )
                return
            self._remember_dashboard_verification(verification)

        # Deliberately bypass the Alpha8.14 presentation-layer compatibility wrapper.
        # The active updater owns convergence in Alpha8.15+ and the base verifier owns
        # transaction completion once every required local component is exact.
        await base.KEMSUpdateOrchestrator.async_verify_pending(self, save=save)

    def _dashboard_current(self) -> bool | None:
        """Verify the exact same generated bytes that the updater writes."""
        target = Path(self.hass.config.path("kems_master_dashboard.yaml"))
        try:
            expected = _managed_dashboard_bytes()
        except (OSError, ValueError) as error:
            self._dashboard_verification_detail = (
                f"Managed dashboard payload could not be generated: {error}"
            )
            self._dashboard_expected_sha256 = None
            self._dashboard_installed_sha256 = None
            return None

        verification = verify_managed_dashboard(target, expected)
        self._remember_dashboard_verification(verification)
        if verification.current:
            return True
        if verification.installed_sha256 is None:
            return None
        return False

    def snapshot(self) -> dict[str, Any]:
        """Expose dashboard convergence evidence alongside normal update diagnostics."""
        snapshot = super().snapshot()
        snapshot["dashboard_verification"] = {
            "detail": self._dashboard_verification_detail,
            "expected_sha256": self._dashboard_expected_sha256,
            "installed_sha256": self._dashboard_installed_sha256,
        }
        return snapshot


async def async_setup_update_orchestrator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ConvergentKEMSUpdateOrchestrator:
    """Set up the strict updater while preserving the existing public services."""
    await _async_converge_dashboard(hass, strict=False)
    orchestrator = ConvergentKEMSUpdateOrchestrator(hass, entry)
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
