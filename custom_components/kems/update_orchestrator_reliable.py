"""Reliability repairs layered over the proven KEMS update orchestrator."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import update_orchestrator as base
from .const import DOMAIN
from .dashboard import _combined_master_dashboard_bytes, _sync_dashboard_bytes

_UPDATE_DASHBOARD_MARKER = (
    "          **Automatic updates are opt-in.** Turn them on below when you are happy "
    "for KEMS to install tested releases unattended. A failed unattended update pauses "
    "automatic updates until you explicitly re-enable them.\n"
)
_UPDATE_DASHBOARD_BUTTON = (
    "      - type: button\n"
    "        name: Check for updates\n"
    "        icon: mdi:refresh\n"
    "        show_state: false\n"
    "        tap_action:\n"
    "          action: perform-action\n"
    "          perform_action: kems.check_for_updates\n"
)
_WINDOW_POLICY_KEYS = frozenset({"maintenance_start", "maintenance_end"})
_WINDOW_EDIT_GUARD = timedelta(seconds=30)

# HACS replaces manifest.json while the old Python process is still running. Capture
# the version at import time so the updater cannot mistake new files on disk for code
# that has actually been activated by a Home Assistant Core restart.
_read_integration_version_from_disk = base._installed_integration_version
_RUNNING_INTEGRATION_VERSION = _read_integration_version_from_disk()


def _running_integration_version() -> str:
    """Return the KEMS version loaded into this Home Assistant Python process."""
    return _RUNNING_INTEGRATION_VERSION


base._installed_integration_version = _running_integration_version


def _is_leading_v_alias(tag: str) -> bool:
    """Return whether a release tag is a conventional leading-v alias."""
    return tag.lower().startswith("v") and len(tag) > 1 and tag[1].isdigit()


def _combined_dashboard_with_update_button_bytes() -> bytes:
    """Return the managed dashboard with a direct update-check button."""
    content = _combined_master_dashboard_bytes().decode("utf-8")
    if _UPDATE_DASHBOARD_BUTTON in content:
        return content.encode()
    if _UPDATE_DASHBOARD_MARKER not in content:
        raise ValueError("Managed KEMS Updates view marker is missing")
    return content.replace(
        _UPDATE_DASHBOARD_MARKER,
        _UPDATE_DASHBOARD_MARKER + _UPDATE_DASHBOARD_BUTTON,
        1,
    ).encode()


async def _async_sync_update_dashboard(hass: HomeAssistant) -> None:
    """Add reliable update controls without making KEMS startup depend on Lovelace."""
    target = Path(hass.config.path("kems_master_dashboard.yaml"))
    try:
        content = await hass.async_add_executor_job(
            _combined_dashboard_with_update_button_bytes
        )
        await hass.async_add_executor_job(_sync_dashboard_bytes, content, target)
    except (OSError, ValueError):
        base.LOGGER.exception("Unable to add KEMS update controls to managed dashboard")


class ReliableKEMSUpdateOrchestrator(base.KEMSUpdateOrchestrator):
    """Keep coordinated updates restart-safe and verification-accurate."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise reliability state for one Home Assistant runtime."""
        super().__init__(hass, entry)
        self._window_edit_guard_until: datetime | None = None

    async def async_set_policy(self, **changes: Any) -> None:
        """Persist policy without letting a partial clock edit start maintenance."""
        keys = set(changes)
        if keys and keys <= _WINDOW_POLICY_KEYS:
            current = asdict(self.policy)
            current.update(changes)
            self.policy = base.UpdatePolicy.from_dict(current)
            self._window_edit_guard_until = base.dt_util.now() + _WINDOW_EDIT_GUARD
            self._reschedule_pending_after_window_edit()
            await self._async_save()
            self._write_legacy_states()
            return

        if (
            changes.get("automatic_updates") is True
            and self.pending
            and self.pending.get("stage") == "failed"
        ):
            self.pending.pop("error", None)
            self.last_error = None
            disruptive = bool(self.pending.get("maintenance", {}).get("required", True))
            self.pending["stage"] = "scheduled" if disruptive else "ready"
            self.pending["scheduled_for"] = (
                self._scheduled_time().isoformat() if disruptive else None
            )
            self.maintenance = self._maintenance_payload(
                "scheduled" if disruptive else "update_available",
                self.pending,
            )
        await super().async_set_policy(**changes)

    def _reschedule_pending_after_window_edit(self) -> None:
        """Recalculate a pending window without executing the transaction."""
        if not self.pending or not self.policy.automatic_updates:
            return
        disruptive = bool(self.pending.get("maintenance", {}).get("required", True))
        if not disruptive:
            return
        stage = str(self.pending.get("stage") or "")
        if stage in {"installing", "restart_requested", "verifying", "failed"}:
            return
        self.pending["scheduled_for"] = self._scheduled_time().isoformat()
        if stage != "installed_waiting_restart":
            self.pending["stage"] = "scheduled"
        self.maintenance = self._maintenance_payload("scheduled", self.pending)

    async def _maybe_run_pending(self) -> None:
        """Never execute while the user may still be editing the window clocks."""
        guard_until = self._window_edit_guard_until
        if guard_until is not None:
            if base.dt_util.now() < guard_until:
                self._reschedule_pending_after_window_edit()
                await self._async_save()
                self._write_legacy_states()
                return
            self._window_edit_guard_until = None
        await super()._maybe_run_pending()

    async def _async_fetch_bundle(self) -> dict[str, Any] | None:
        """Fetch the highest complete canonical KEMS bundle release."""
        session = async_get_clientsession(self.hass)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "KEMS-Home-Assistant-Update-Orchestrator",
        }
        async with session.get(
            base.GITHUB_RELEASES_URL,
            headers=headers,
            timeout=15,
        ) as response:
            if response.status >= 400:
                raise HomeAssistantError(
                    f"GitHub bundle lookup returned HTTP {response.status}"
                )
            releases = await response.json()
        if not isinstance(releases, list):
            raise HomeAssistantError(
                "GitHub bundle lookup returned an invalid response"
            )

        candidates: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = (
            []
        )
        for release in releases:
            if release.get("draft"):
                continue
            if self.policy.channel == "stable" and release.get("prerelease"):
                continue
            release_tag = str(release.get("tag_name") or "").strip()
            if not release_tag or _is_leading_v_alias(release_tag):
                continue
            version = base._normalise_version(release_tag)
            if base.version_relation(version, version) != 0:
                continue
            assets = release.get("assets") or []
            manifest = next(
                (item for item in assets if item.get("name") == base.BUNDLE_ASSET),
                None,
            )
            checksum = next(
                (
                    item
                    for item in assets
                    if item.get("name") == base.BUNDLE_CHECKSUM_ASSET
                ),
                None,
            )
            if manifest is None or checksum is None:
                continue
            candidates.append((version, release, manifest, checksum))

        if not candidates:
            return None

        selected_version, selected, manifest_asset, checksum_asset = candidates[0]
        for candidate in candidates[1:]:
            relation = base.version_relation(candidate[0], selected_version)
            if relation == 1:
                selected_version, selected, manifest_asset, checksum_asset = candidate

        async def download(asset: dict[str, Any]) -> bytes:
            url = str(asset.get("browser_download_url") or "")
            if not url:
                raise HomeAssistantError(
                    "KEMS bundle release asset has no download URL"
                )
            async with session.get(
                url,
                headers={"User-Agent": headers["User-Agent"]},
                timeout=15,
            ) as response:
                if response.status >= 400:
                    raise HomeAssistantError(
                        f"KEMS bundle asset download returned HTTP {response.status}"
                    )
                return await response.read()

        manifest_bytes, checksum_bytes = await asyncio.gather(
            download(manifest_asset),
            download(checksum_asset),
        )
        expected = checksum_bytes.decode("utf-8", errors="replace").strip().split()[0]
        observed = hashlib.sha256(manifest_bytes).hexdigest()
        if not expected or expected.lower() != observed.lower():
            raise HomeAssistantError("KEMS bundle SHA-256 verification failed")
        try:
            bundle = base._validated_bundle(json.loads(manifest_bytes))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise HomeAssistantError(f"Invalid KEMS bundle: {error}") from error

        release_tag = str(selected.get("tag_name") or "").strip()
        core_target = base._component_target(bundle, "kems_core")
        if (
            core_target
            and release_tag
            and not base._version_matches(core_target, release_tag)
        ):
            raise HomeAssistantError(
                f"KEMS bundle targets {core_target}, but release tag is {release_tag}"
            )
        bundle["release"] = {
            "tag": release_tag or None,
            "name": selected.get("name"),
            "published_at": selected.get("published_at"),
            "prerelease": bool(selected.get("prerelease")),
            "sha256": observed,
        }
        return bundle

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

    def _refresh_component_status(self) -> None:
        """Show files-staged-for-restart separately from genuinely running code."""
        super()._refresh_component_status()
        files_version = _read_integration_version_from_disk()
        for item in self.component_status:
            if item.key != "kems_core" or not item.target:
                continue
            if base._version_matches(
                files_version, item.target
            ) and not base._version_matches(
                _RUNNING_INTEGRATION_VERSION,
                item.target,
            ):
                item.status = "restart-required"
                item.detail = (
                    "Target files are installed, but Home Assistant Core has not "
                    "restarted into them yet"
                )

    def _dashboard_current(self) -> bool | None:
        """Verify the installed dashboard against the combined managed file."""
        installed = Path(self.hass.config.path("kems_master_dashboard.yaml"))
        try:
            return (
                installed.read_bytes() == _combined_dashboard_with_update_button_bytes()
            )
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

    def snapshot(self) -> dict[str, Any]:
        """Expose running-versus-on-disk version truth for diagnostics and UI."""
        snapshot = super().snapshot()
        files_version = _read_integration_version_from_disk()
        snapshot["running_kems_version"] = _RUNNING_INTEGRATION_VERSION
        snapshot["installed_files_kems_version"] = files_version
        snapshot["restart_activation_pending"] = not base._version_matches(
            _RUNNING_INTEGRATION_VERSION,
            files_version,
        )
        return snapshot


async def async_setup_update_orchestrator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ReliableKEMSUpdateOrchestrator:
    """Set up the reliable orchestrator while preserving the existing public API."""
    await _async_sync_update_dashboard(hass)
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
