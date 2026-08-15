"""Coordinated KEMS updates, maintenance windows and component verification."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import KEMSEntity

LOGGER = logging.getLogger(__name__)

DATA_KEY = "kems_update_orchestrators"
STORE_VERSION = 1
STORE_KEY_PREFIX = "kems.update_orchestrator"
CHECK_INTERVAL = timedelta(minutes=15)
INITIAL_CHECK_DELAY_SECONDS = 30
BUNDLE_REPOSITORY = "kylejago/KEMS"
BUNDLE_ASSET = "kems-bundle.json"
BUNDLE_CHECKSUM_ASSET = f"{BUNDLE_ASSET}.sha256"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{BUNDLE_REPOSITORY}/releases?per_page=30"
NOTIFICATION_ID = "kems_update_maintenance"
EVENT_MAINTENANCE = "kems_maintenance_notice"

SERVICE_CHECK_UPDATES = "check_for_updates"
SERVICE_APPLY_UPDATE = "apply_update"
SERVICE_CANCEL_UPDATE = "cancel_scheduled_update"

UPDATE_MODE_SAFE_FIRST = "Automatic safe-first"
UPDATE_MODE_WINDOW = "All changes in maintenance window"
UPDATE_MODES = (UPDATE_MODE_SAFE_FIRST, UPDATE_MODE_WINDOW)


@dataclass(slots=True)
class UpdatePolicy:
    """User-controlled automatic-update policy."""

    automatic_updates: bool = False
    mode: str = UPDATE_MODE_SAFE_FIRST
    maintenance_start: str = "03:00"
    maintenance_end: str = "04:00"
    automatic_restart: bool = True
    backup_before_update: bool = True
    notify_before_disruption: bool = True
    channel: str = "alpha"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "UpdatePolicy":
        """Load a policy while discarding unknown or invalid values."""
        raw = raw or {}
        mode = str(raw.get("mode", UPDATE_MODE_SAFE_FIRST))
        if mode not in UPDATE_MODES:
            mode = UPDATE_MODE_SAFE_FIRST
        channel = "stable" if str(raw.get("channel", "alpha")) == "stable" else "alpha"
        start = _clock_text(raw.get("maintenance_start"), "03:00")
        end = _clock_text(raw.get("maintenance_end"), "04:00")
        return cls(
            automatic_updates=bool(raw.get("automatic_updates", False)),
            mode=mode,
            maintenance_start=start,
            maintenance_end=end,
            automatic_restart=bool(raw.get("automatic_restart", True)),
            backup_before_update=bool(raw.get("backup_before_update", True)),
            notify_before_disruption=bool(raw.get("notify_before_disruption", True)),
            channel=channel,
        )


@dataclass(slots=True)
class ComponentStatus:
    """One component's target and observed state."""

    key: str
    target: str | None
    installed: str | None
    status: str
    delivery: str
    required: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly component data."""
        return asdict(self)


def _clock_text(value: Any, fallback: str) -> str:
    """Return a strict HH:MM clock value."""
    text = str(value or "").strip()
    try:
        parsed = time.fromisoformat(text)
    except ValueError:
        return fallback
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _parse_clock(value: str) -> time:
    """Parse one persisted maintenance clock."""
    return time.fromisoformat(_clock_text(value, "00:00"))


def _inside_window(now: datetime, start: time, end: time) -> bool:
    """Return whether local time is inside a possibly overnight window."""
    current = now.timetz().replace(tzinfo=None)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _next_window_start(now: datetime, start: time, end: time) -> datetime:
    """Return the current or next maintenance-window start."""
    if _inside_window(now, start, end):
        return now
    candidate = now.replace(
        hour=start.hour,
        minute=start.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _normalise_version(value: Any) -> str:
    """Normalise a release version for safe comparison."""
    text = str(value or "").strip()
    if text.lower().startswith("v") and len(text) > 1 and text[1].isdigit():
        return text[1:]
    return text


def _version_matches(first: Any, second: Any) -> bool:
    """Compare versions while tolerating a conventional leading v."""
    return bool(first and second) and _normalise_version(first) == _normalise_version(second)


def _validated_bundle(raw: Any) -> dict[str, Any]:
    """Validate the subset of the shared bundle contract KEMS consumes."""
    if not isinstance(raw, dict):
        raise ValueError("KEMS bundle must be a JSON object")
    if int(raw.get("schema", 0)) != 1:
        raise ValueError("Unsupported KEMS bundle schema")
    bundle = str(raw.get("bundle", "")).strip()
    if not bundle:
        raise ValueError("KEMS bundle has no bundle version")
    components = raw.get("components")
    if not isinstance(components, dict):
        raise ValueError("KEMS bundle has no components object")
    core = components.get("kems_core")
    if core is not None:
        if not isinstance(core, dict) or not str(core.get("version", "")).strip():
            raise ValueError("KEMS bundle kems_core target is invalid")
    maintenance = raw.get("maintenance", {})
    if not isinstance(maintenance, dict):
        raise ValueError("KEMS bundle maintenance section is invalid")
    return {
        **raw,
        "bundle": bundle,
        "components": components,
        "maintenance": maintenance,
    }


def _installed_integration_version() -> str:
    """Read the running KEMS manifest version."""
    try:
        payload = json.loads(Path(__file__).with_name("manifest.json").read_text("utf-8"))
        return str(payload.get("version") or "unknown")
    except (OSError, ValueError, TypeError):
        return "unknown"


def _component_target(bundle: dict[str, Any] | None, key: str) -> str | None:
    """Return one optional component version from a bundle."""
    component = (bundle or {}).get("components", {}).get(key)
    if not isinstance(component, dict):
        return None
    value = component.get("version")
    return str(value).strip() if value not in {None, ""} else None


def _component_required(bundle: dict[str, Any] | None, key: str) -> bool:
    """Return whether a bundle marks a component as required."""
    component = (bundle or {}).get("components", {}).get(key)
    return bool(isinstance(component, dict) and component.get("required", False))


def _component_delivery(bundle: dict[str, Any] | None, key: str) -> str:
    """Return the delivery agent named in the shared bundle."""
    component = (bundle or {}).get("components", {}).get(key)
    if not isinstance(component, dict):
        return "not-targeted"
    return str(component.get("delivery") or "coordinated")


class KEMSUpdateOrchestrator:
    """Converge this Home Assistant installation on the published KEMS bundle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise update state without performing network I/O."""
        self.hass = hass
        self.entry = entry
        self.store = Store(
            hass,
            STORE_VERSION,
            f"{STORE_KEY_PREFIX}.{entry.entry_id}",
        )
        self.policy = UpdatePolicy()
        self.latest_bundle: dict[str, Any] | None = None
        self.bundle_source = "none"
        self.last_checked: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        self.maintenance: dict[str, Any] = {"status": "none"}
        self.history: list[dict[str, Any]] = []
        self.last_error: str | None = None
        self.component_status: list[ComponentStatus] = []
        self._lock = asyncio.Lock()
        self._unsub_interval = None
        self._unsub_initial = None

    async def async_start(self) -> None:
        """Restore durable state and start periodic checks."""
        stored = await self.store.async_load() or {}
        self.policy = UpdatePolicy.from_dict(stored.get("policy"))
        self.last_result = stored.get("last_result")
        self.pending = stored.get("pending")
        self.maintenance = stored.get("maintenance") or {"status": "none"}
        self.history = list(stored.get("history") or [])[-20:]
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._periodic_check,
            CHECK_INTERVAL,
        )
        self._unsub_initial = async_call_later(
            self.hass,
            INITIAL_CHECK_DELAY_SECONDS,
            self._initial_check,
        )
        await self.async_verify_pending()
        self._write_legacy_states()

    async def async_stop(self) -> None:
        """Stop timers and persist the latest state."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        if self._unsub_initial is not None:
            self._unsub_initial()
            self._unsub_initial = None
        await self._async_save()

    async def _initial_check(self, _now: datetime) -> None:
        await self.async_check()

    async def _periodic_check(self, _now: datetime) -> None:
        await self.async_check()

    async def _async_save(self) -> None:
        """Persist policy, pending transaction and recent history."""
        await self.store.async_save(
            {
                "policy": asdict(self.policy),
                "last_result": self.last_result,
                "pending": self.pending,
                "maintenance": self.maintenance,
                "history": self.history[-20:],
            }
        )

    async def async_set_policy(self, **changes: Any) -> None:
        """Persist selected policy fields without reloading KEMS."""
        current = asdict(self.policy)
        current.update(changes)
        self.policy = UpdatePolicy.from_dict(current)
        await self._async_save()
        self._write_legacy_states()
        await self.async_check(force=True)

    async def async_check(self, *, force: bool = False) -> dict[str, Any]:
        """Fetch the latest coordinated bundle and decide the next action."""
        if self._lock.locked() and not force:
            return self.snapshot()
        async with self._lock:
            self.last_error = None
            try:
                bundle = await self._async_fetch_bundle()
                if bundle is None:
                    bundle = self._standalone_bundle_from_update_entity()
                    self.bundle_source = "home-assistant-update-entity" if bundle else "none"
                else:
                    self.bundle_source = "github-release-bundle"
                self.latest_bundle = bundle
                self.last_checked = dt_util.now().isoformat()
                self._refresh_component_status()
                await self.async_verify_pending(save=False)
                if bundle is not None:
                    await self._consider_bundle(bundle)
            except Exception as error:  # defensive boundary around unattended updates
                LOGGER.exception("KEMS automatic update check failed")
                self.last_error = str(error)
            await self._async_save()
            self._write_legacy_states()
            return self.snapshot()

    async def _async_fetch_bundle(self) -> dict[str, Any] | None:
        """Fetch and SHA-256 verify the newest bundle release asset."""
        session = async_get_clientsession(self.hass)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "KEMS-Home-Assistant-Update-Orchestrator",
        }
        async with session.get(GITHUB_RELEASES_URL, headers=headers, timeout=15) as response:
            if response.status >= 400:
                raise HomeAssistantError(f"GitHub bundle lookup returned HTTP {response.status}")
            releases = await response.json()
        if not isinstance(releases, list):
            raise HomeAssistantError("GitHub bundle lookup returned an invalid response")
        selected: dict[str, Any] | None = None
        manifest_asset: dict[str, Any] | None = None
        checksum_asset: dict[str, Any] | None = None
        for release in releases:
            if release.get("draft"):
                continue
            if self.policy.channel == "stable" and release.get("prerelease"):
                continue
            assets = release.get("assets") or []
            manifest = next((item for item in assets if item.get("name") == BUNDLE_ASSET), None)
            checksum = next(
                (item for item in assets if item.get("name") == BUNDLE_CHECKSUM_ASSET),
                None,
            )
            if manifest is None:
                continue
            if checksum is None:
                raise HomeAssistantError(
                    f"Release {release.get('tag_name')} has a KEMS bundle without its SHA-256 asset"
                )
            selected = release
            manifest_asset = manifest
            checksum_asset = checksum
            break
        if selected is None or manifest_asset is None or checksum_asset is None:
            return None

        async def download(asset: dict[str, Any]) -> bytes:
            url = str(asset.get("browser_download_url") or "")
            if not url:
                raise HomeAssistantError("KEMS bundle release asset has no download URL")
            async with session.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=15) as response:
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
            bundle = _validated_bundle(json.loads(manifest_bytes))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise HomeAssistantError(f"Invalid KEMS bundle: {error}") from error
        bundle["release"] = {
            "tag": selected.get("tag_name"),
            "name": selected.get("name"),
            "published_at": selected.get("published_at"),
            "prerelease": bool(selected.get("prerelease")),
            "sha256": observed,
        }
        return bundle

    def _find_kems_update_entity(self):
        """Find the HACS/Home Assistant update entity for this integration."""
        preferred = self.hass.states.get("update.kems_update")
        if preferred is not None:
            return preferred
        direct = self.hass.states.get("update.kems")
        if direct is not None:
            return direct
        for state in self.hass.states.async_all("update"):
            name = str(state.attributes.get("friendly_name") or "").lower()
            title = str(state.attributes.get("title") or "").lower()
            if "kems" in name or title == "kems":
                return state
        return None

    def _standalone_bundle_from_update_entity(self) -> dict[str, Any] | None:
        """Retain automatic KEMS updates even before bundle assets are published."""
        state = self._find_kems_update_entity()
        if state is None:
            return None
        latest = state.attributes.get("latest_version")
        installed = state.attributes.get("installed_version")
        if not latest or _version_matches(latest, installed):
            return None
        return {
            "schema": 1,
            "bundle": f"standalone-{latest}",
            "channel": "alpha",
            "components": {
                "kems_core": {
                    "version": str(latest),
                    "required": True,
                    "delivery": "home-assistant-update",
                    "restart": "home_assistant",
                },
                "dashboard": {
                    "version": str(latest),
                    "required": True,
                    "delivery": "kems_core",
                },
            },
            "maintenance": {
                "required": True,
                "reason": f"KEMS {latest} requires Home Assistant to restart",
                "expected_downtime_minutes": 5,
                "home_assistant_restart_required": True,
                "reboot_required": False,
                "affected_components": ["kems_core", "dashboard"],
            },
            "release": {
                "tag": latest,
                "name": f"KEMS {latest}",
                "prerelease": True,
                "fallback": True,
            },
        }

    async def _consider_bundle(self, bundle: dict[str, Any]) -> None:
        """Schedule or apply the local part of a bundle."""
        target = _component_target(bundle, "kems_core")
        current = _installed_integration_version()
        if not target or _version_matches(current, target):
            return
        if self.pending and _version_matches(self.pending.get("target"), target):
            await self._maybe_run_pending()
            return

        maintenance = bundle.get("maintenance") or {}
        reason = str(
            maintenance.get("reason")
            or f"Install KEMS {target} and restart Home Assistant"
        )
        disruptive = bool(
            maintenance.get("required")
            or maintenance.get("home_assistant_restart_required", True)
        )
        scheduled_for = None
        if disruptive:
            scheduled_for = self._scheduled_time().isoformat()
        self.pending = {
            "bundle": bundle.get("bundle"),
            "target": target,
            "discovered_at": dt_util.now().isoformat(),
            "scheduled_for": scheduled_for,
            "stage": "scheduled" if disruptive else "ready",
            "reason": reason,
            "maintenance": maintenance,
            "source": self.bundle_source,
        }
        self.maintenance = self._maintenance_payload("scheduled", self.pending)
        if self.policy.notify_before_disruption:
            await self._async_notify("scheduled", self.pending)
        if self.policy.automatic_updates:
            await self._maybe_run_pending()

    def _scheduled_time(self) -> datetime:
        """Resolve the next configured maintenance window."""
        now = dt_util.now()
        return _next_window_start(
            now,
            _parse_clock(self.policy.maintenance_start),
            _parse_clock(self.policy.maintenance_end),
        )

    def _in_maintenance_window(self) -> bool:
        """Return whether now is in the configured local maintenance window."""
        return _inside_window(
            dt_util.now(),
            _parse_clock(self.policy.maintenance_start),
            _parse_clock(self.policy.maintenance_end),
        )

    async def _maybe_run_pending(self) -> None:
        """Run a pending transaction only when the policy permits it."""
        if not self.pending or not self.policy.automatic_updates:
            return
        disruptive = bool(self.pending.get("maintenance", {}).get("required", True))
        if disruptive and not self._in_maintenance_window():
            return
        if self.policy.mode == UPDATE_MODE_WINDOW and not self._in_maintenance_window():
            return
        await self.async_apply_pending(force=False)

    async def async_apply_pending(self, *, force: bool) -> None:
        """Install the exact KEMS target and restart when permitted."""
        if self._lock.locked() and force:
            # A service can arrive while the periodic check owns the lock.  The
            # caller will receive the current state and the next check will act.
            return
        pending = self.pending
        if pending is None:
            await self.async_check(force=True)
            pending = self.pending
        if pending is None:
            return
        if not force and not self.policy.automatic_updates:
            return
        if not force and bool(pending.get("maintenance", {}).get("required", True)) and not self._in_maintenance_window():
            return

        target = str(pending.get("target") or "")
        state = self._find_kems_update_entity()
        if state is None:
            await self._fail_pending("KEMS update entity is not available")
            return
        latest = state.attributes.get("latest_version")
        installed = state.attributes.get("installed_version")
        if _version_matches(installed, target):
            pending["stage"] = "installed_waiting_restart"
        else:
            if latest and not _version_matches(latest, target):
                await self._fail_pending(
                    f"Home Assistant offers {latest}, but bundle requires {target}"
                )
                return
            if self.policy.backup_before_update:
                if self.hass.services.has_service("backup", "create_automatic"):
                    try:
                        await self.hass.services.async_call(
                            "backup",
                            "create_automatic",
                            {},
                            blocking=True,
                        )
                    except Exception as error:  # backup must be a hard gate
                        await self._fail_pending(f"Pre-update backup failed: {error}")
                        return
                else:
                    LOGGER.warning(
                        "KEMS pre-update backup requested but backup.create_automatic is unavailable"
                    )
            if not self.hass.services.has_service("update", "install"):
                await self._fail_pending("Home Assistant update.install service is unavailable")
                return
            pending["stage"] = "installing"
            self.maintenance = self._maintenance_payload("in_progress", pending)
            await self._async_notify("in_progress", pending)
            await self._async_save()
            try:
                await self.hass.services.async_call(
                    "update",
                    "install",
                    {"entity_id": state.entity_id, "version": target},
                    blocking=True,
                )
            except Exception as error:
                await self._fail_pending(f"KEMS installation failed: {error}")
                return
            pending["installed_at"] = dt_util.now().isoformat()
            pending["stage"] = "installed_waiting_restart"

        restart_required = bool(
            pending.get("maintenance", {}).get("home_assistant_restart_required", True)
        )
        if not restart_required:
            await self.async_verify_pending()
            return
        if not self.policy.automatic_restart and not force:
            pending["stage"] = "waiting_for_restart_approval"
            self.maintenance = self._maintenance_payload("scheduled", pending)
            await self._async_notify("restart_required", pending)
            await self._async_save()
            return
        if not force and not self._in_maintenance_window():
            pending["stage"] = "waiting_for_maintenance_window"
            pending["scheduled_for"] = self._scheduled_time().isoformat()
            self.maintenance = self._maintenance_payload("scheduled", pending)
            await self._async_save()
            return
        if not self.hass.services.has_service("homeassistant", "restart"):
            await self._fail_pending("Home Assistant restart service is unavailable")
            return

        pending["stage"] = "restart_requested"
        pending["restart_requested_at"] = dt_util.now().isoformat()
        self.maintenance = self._maintenance_payload("in_progress", pending)
        await self._async_notify("restart", pending)
        await self._async_save()
        self._write_legacy_states()
        await self.hass.services.async_call(
            "homeassistant",
            "restart",
            {},
            blocking=False,
        )

    async def async_verify_pending(self, *, save: bool = True) -> None:
        """Verify exact versions after a coordinated restart."""
        self._refresh_component_status()
        if not self.pending:
            if save:
                await self._async_save()
            return
        target = self.pending.get("target")
        core_current = _version_matches(_installed_integration_version(), target)
        local_required = [
            item
            for item in self.component_status
            if item.required and item.delivery != "external"
        ]
        all_local_current = bool(core_current) and all(
            item.status in {"current", "not-targeted", "not-installed"}
            for item in local_required
        )
        if all_local_current:
            completed = {
                "bundle": self.pending.get("bundle"),
                "target": target,
                "completed_at": dt_util.now().isoformat(),
                "result": "success",
                "components": [item.to_dict() for item in self.component_status],
            }
            self.last_result = completed
            self.history.append(completed)
            self.history = self.history[-20:]
            previous = self.pending
            self.pending = None
            self.maintenance = self._maintenance_payload("completed", previous)
            await self._async_notify("completed", previous)
        elif self.pending.get("stage") == "restart_requested":
            self.pending["stage"] = "verifying"
            self.maintenance = self._maintenance_payload("verifying", self.pending)
        if save:
            await self._async_save()
        self._write_legacy_states()

    async def async_cancel(self) -> None:
        """Cancel a scheduled transaction that has not started installing."""
        if self.pending and self.pending.get("stage") not in {
            "installing",
            "installed_waiting_restart",
            "restart_requested",
            "verifying",
        }:
            cancelled = {
                "bundle": self.pending.get("bundle"),
                "target": self.pending.get("target"),
                "completed_at": dt_util.now().isoformat(),
                "result": "cancelled",
            }
            self.history.append(cancelled)
            self.last_result = cancelled
            self.pending = None
            self.maintenance = {"status": "none"}
            await self._async_save()
            self._write_legacy_states()

    async def _fail_pending(self, message: str) -> None:
        """Record a durable failed transaction and retain the reason."""
        pending = self.pending or {}
        failed = {
            "bundle": pending.get("bundle"),
            "target": pending.get("target"),
            "completed_at": dt_util.now().isoformat(),
            "result": "failed",
            "error": message,
        }
        self.last_error = message
        self.last_result = failed
        self.history.append(failed)
        self.history = self.history[-20:]
        if self.pending is not None:
            self.pending["stage"] = "failed"
            self.pending["error"] = message
        self.maintenance = self._maintenance_payload("failed", self.pending or failed)
        await self._async_notify("failed", self.pending or failed)
        await self._async_save()
        self._write_legacy_states()

    def _dashboard_current(self) -> bool | None:
        """Verify that the managed dashboard is byte-identical to its package."""
        packaged = Path(__file__).with_name("kems_master_dashboard.yaml")
        installed = Path(self.hass.config.path("kems_master_dashboard.yaml"))
        try:
            return installed.read_bytes() == packaged.read_bytes()
        except OSError:
            return None

    def _refresh_component_status(self) -> None:
        """Build local verification and delegated external-target status."""
        bundle = self.latest_bundle
        statuses: list[ComponentStatus] = []
        running = _installed_integration_version()
        core_target = _component_target(bundle, "kems_core")
        if core_target is None:
            core_status = "not-targeted"
        else:
            core_status = "current" if _version_matches(running, core_target) else "update-required"
        statuses.append(
            ComponentStatus(
                "kems_core",
                core_target,
                running,
                core_status,
                "home-assistant",
                _component_required(bundle, "kems_core"),
            )
        )

        dashboard_target = _component_target(bundle, "dashboard")
        dashboard_current = self._dashboard_current()
        dashboard_status = "not-targeted"
        if dashboard_target is not None:
            if dashboard_current is True and (
                core_target is None or _version_matches(running, core_target)
            ):
                dashboard_status = "current"
            elif dashboard_current is False:
                dashboard_status = "update-required"
            else:
                dashboard_status = "waiting"
        statuses.append(
            ComponentStatus(
                "dashboard",
                dashboard_target,
                running if dashboard_current is True else None,
                dashboard_status,
                "kems_core",
                _component_required(bundle, "dashboard"),
                "Managed dashboard hash matches packaged YAML" if dashboard_current is True else "",
            )
        )

        panel_target = _component_target(bundle, "panel")
        panel_state = self.hass.states.get("sensor.kems_panel_firmware_version")
        panel_installed = None
        if panel_state is not None and panel_state.state not in {"unknown", "unavailable"}:
            panel_installed = panel_state.state
        if panel_target is None:
            panel_status = "not-targeted"
        elif panel_installed is None:
            panel_status = "not-installed"
        else:
            panel_status = "current" if _version_matches(panel_installed, panel_target) else "verifying"
        statuses.append(
            ComponentStatus(
                "panel",
                panel_target,
                panel_installed,
                panel_status,
                "kems_core",
                _component_required(bundle, "panel"),
            )
        )

        for key in ("property_web", "pi_agent", "pi_system", "public_web"):
            target = _component_target(bundle, key)
            statuses.append(
                ComponentStatus(
                    key,
                    target,
                    None,
                    "delegated" if target is not None else "not-targeted",
                    "external",
                    _component_required(bundle, key),
                    "Verified by that component's own bundle agent",
                )
            )
        self.component_status = statuses

    def _maintenance_payload(self, status: str, pending: dict[str, Any]) -> dict[str, Any]:
        """Build the same notice shape used by every KEMS user surface."""
        maintenance = pending.get("maintenance") or {}
        return {
            "status": status,
            "bundle": pending.get("bundle"),
            "target": pending.get("target"),
            "scheduled_for": pending.get("scheduled_for"),
            "reason": pending.get("reason") or maintenance.get("reason"),
            "expected_downtime_minutes": maintenance.get("expected_downtime_minutes", 5),
            "affected_components": list(maintenance.get("affected_components") or ["kems_core"]),
            "home_assistant_restart_required": bool(
                maintenance.get("home_assistant_restart_required", True)
            ),
            "reboot_required": bool(maintenance.get("reboot_required", False)),
            "updated_at": dt_util.now().isoformat(),
        }

    async def _async_notify(self, phase: str, pending: dict[str, Any]) -> None:
        """Publish one persistent notice and one HA event for all user areas."""
        notice = self._maintenance_payload(
            "completed" if phase == "completed" else "failed" if phase == "failed" else "in_progress" if phase in {"in_progress", "restart"} else "scheduled",
            pending,
        )
        self.hass.bus.async_fire(EVENT_MAINTENANCE, notice)
        if not self.hass.services.has_service("persistent_notification", "create"):
            return
        scheduled = notice.get("scheduled_for")
        when = "the configured maintenance window"
        if scheduled:
            try:
                when = dt_util.as_local(datetime.fromisoformat(str(scheduled))).strftime("%a %d %b %H:%M")
            except ValueError:
                pass
        reason = str(notice.get("reason") or "KEMS coordinated update")
        downtime = notice.get("expected_downtime_minutes") or 5
        target = pending.get("target") or notice.get("target") or "the new release"
        if phase == "completed":
            title = "KEMS maintenance complete"
            message = f"KEMS {target} is active and all required local components passed verification. Everything is up to date."
        elif phase == "failed":
            title = "KEMS maintenance needs attention"
            message = f"The coordinated update did not complete: {pending.get('error') or self.last_error or reason}"
        elif phase == "restart_required":
            title = "KEMS update staged — restart approval required"
            message = f"KEMS {target} is installed. Home Assistant must restart to activate it. Reason: {reason}."
        elif phase == "restart":
            title = "KEMS maintenance in progress"
            message = f"Home Assistant is restarting to activate KEMS {target}. Expected interruption: about {downtime} minutes."
        elif phase == "in_progress":
            title = "KEMS maintenance in progress"
            message = f"Installing KEMS {target}. Reason: {reason}."
        else:
            title = "Planned KEMS maintenance"
            message = f"KEMS {target} is scheduled for {when}. Reason: {reason}. Expected interruption: about {downtime} minutes. No action is required."
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": NOTIFICATION_ID,
            },
            blocking=True,
        )

    def status_label(self) -> str:
        """Return the headline Home Assistant status."""
        if self.last_error:
            return "Attention required"
        if self.pending:
            stage = str(self.pending.get("stage") or "scheduled")
            if stage in {"installing", "restart_requested", "verifying"}:
                return "Updating"
            return "Update scheduled"
        if self.latest_bundle is None:
            return "Up to date" if self.last_checked else "Checking"
        required_local = [
            item
            for item in self.component_status
            if item.required and item.delivery != "external"
        ]
        if any(item.status not in {"current", "not-targeted", "not-installed"} for item in required_local):
            return "Update available"
        return "Up to date"

    def snapshot(self) -> dict[str, Any]:
        """Return non-secret diagnostics/UI state."""
        return {
            "status": self.status_label(),
            "policy": asdict(self.policy),
            "bundle": self.latest_bundle.get("bundle") if self.latest_bundle else None,
            "bundle_source": self.bundle_source,
            "release": self.latest_bundle.get("release") if self.latest_bundle else None,
            "last_checked": self.last_checked,
            "pending": self.pending,
            "maintenance": self.maintenance,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "components": [item.to_dict() for item in self.component_status],
            "history": self.history[-10:],
            "running_kems_version": _installed_integration_version(),
        }

    def _write_legacy_states(self) -> None:
        """Publish lightweight states even before the entity platforms refresh."""
        snapshot = self.snapshot()
        self.hass.states.async_set(
            "sensor.kems_update_orchestrator_runtime",
            snapshot["status"],
            {
                "friendly_name": "KEMS update orchestrator runtime",
                **snapshot,
            },
        )
        maintenance = snapshot.get("maintenance") or {"status": "none"}
        self.hass.states.async_set(
            "sensor.kems_maintenance_runtime",
            maintenance.get("status", "none"),
            {
                "friendly_name": "KEMS maintenance runtime",
                **maintenance,
            },
        )


def get_update_orchestrator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> KEMSUpdateOrchestrator | None:
    """Return the orchestrator for a config entry."""
    return hass.data.get(DATA_KEY, {}).get(entry.entry_id)


async def async_setup_update_orchestrator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> KEMSUpdateOrchestrator:
    """Set up one durable orchestrator and shared services."""
    orchestrator = KEMSUpdateOrchestrator(hass, entry)
    hass.data.setdefault(DATA_KEY, {})[entry.entry_id] = orchestrator
    await orchestrator.async_start()

    if not hass.services.has_service(DOMAIN, SERVICE_CHECK_UPDATES):

        async def check_updates(_call: ServiceCall) -> None:
            current = _first_orchestrator(hass)
            if current is not None:
                await current.async_check(force=True)

        async def apply_update(call: ServiceCall) -> None:
            current = _first_orchestrator(hass)
            if current is not None:
                await current.async_apply_pending(force=bool(call.data.get("force", False)))

        async def cancel_update(_call: ServiceCall) -> None:
            current = _first_orchestrator(hass)
            if current is not None:
                await current.async_cancel()

        hass.services.async_register(DOMAIN, SERVICE_CHECK_UPDATES, check_updates)
        hass.services.async_register(DOMAIN, SERVICE_APPLY_UPDATE, apply_update)
        hass.services.async_register(DOMAIN, SERVICE_CANCEL_UPDATE, cancel_update)
    return orchestrator


async def async_unload_update_orchestrator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Unload one orchestrator and remove shared services when unused."""
    orchestrators = hass.data.get(DATA_KEY, {})
    orchestrator = orchestrators.pop(entry.entry_id, None)
    if orchestrator is not None:
        await orchestrator.async_stop()
    if not orchestrators:
        hass.data.pop(DATA_KEY, None)
        for service in (
            SERVICE_CHECK_UPDATES,
            SERVICE_APPLY_UPDATE,
            SERVICE_CANCEL_UPDATE,
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)


def _first_orchestrator(hass: HomeAssistant) -> KEMSUpdateOrchestrator | None:
    """Return the sole KEMS orchestrator."""
    values = list(hass.data.get(DATA_KEY, {}).values())
    return values[0] if values else None


def update_orchestrator_snapshot(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return update diagnostics without requiring network I/O."""
    orchestrator = get_update_orchestrator(hass, entry)
    return orchestrator.snapshot() if orchestrator is not None else {"status": "unavailable"}


def build_update_sensor_entities(
    hass: HomeAssistant,
    coordinator,
    entry: ConfigEntry,
) -> list[SensorEntity]:
    """Build proper entity-registry sensors backed by the orchestrator."""
    orchestrator = get_update_orchestrator(hass, entry)
    if orchestrator is None:
        return []
    return [
        KEMSUpdateStatusSensor(coordinator, orchestrator),
        KEMSMaintenanceStatusSensor(coordinator, orchestrator),
    ]


def build_update_switch_entities(
    hass: HomeAssistant,
    coordinator,
    entry: ConfigEntry,
) -> list[SwitchEntity]:
    """Build update-policy switches."""
    orchestrator = get_update_orchestrator(hass, entry)
    if orchestrator is None:
        return []
    return [
        KEMSAutomaticUpdatesSwitch(coordinator, orchestrator),
        KEMSAutomaticRestartSwitch(coordinator, orchestrator),
        KEMSBackupBeforeUpdateSwitch(coordinator, orchestrator),
    ]


def build_update_select_entities(
    hass: HomeAssistant,
    coordinator,
    entry: ConfigEntry,
) -> list[SelectEntity]:
    """Build update-policy selectors."""
    orchestrator = get_update_orchestrator(hass, entry)
    if orchestrator is None:
        return []
    return [KEMSUpdateModeSelect(coordinator, orchestrator)]


def build_update_time_entities(
    hass: HomeAssistant,
    coordinator,
    entry: ConfigEntry,
) -> list[TimeEntity]:
    """Build maintenance-window time controls."""
    orchestrator = get_update_orchestrator(hass, entry)
    if orchestrator is None:
        return []
    return [
        KEMSMaintenanceStartTime(coordinator, orchestrator),
        KEMSMaintenanceEndTime(coordinator, orchestrator),
    ]


class KEMSUpdateStatusSensor(KEMSEntity, SensorEntity):
    """Headline coordinated update state."""

    _attr_name = "Update status"
    _attr_icon = "mdi:update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, "update_status")
        self.orchestrator = orchestrator

    @property
    def native_value(self) -> str:
        return self.orchestrator.status_label()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.orchestrator.snapshot()


class KEMSMaintenanceStatusSensor(KEMSEntity, SensorEntity):
    """Current/scheduled maintenance notice."""

    _attr_name = "Maintenance status"
    _attr_icon = "mdi:wrench-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, "maintenance_status")
        self.orchestrator = orchestrator

    @property
    def native_value(self) -> str:
        return str(self.orchestrator.maintenance.get("status") or "none")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.orchestrator.maintenance)


class _UpdatePolicySwitch(KEMSEntity, SwitchEntity):
    """Base class for update-policy switches."""

    _attr_entity_category = EntityCategory.CONFIG
    policy_key = ""

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator, key: str) -> None:
        super().__init__(coordinator, key)
        self.orchestrator = orchestrator

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.orchestrator.policy, self.policy_key))

    async def async_turn_on(self, **kwargs) -> None:
        await self.orchestrator.async_set_policy(**{self.policy_key: True})
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.orchestrator.async_set_policy(**{self.policy_key: False})
        self.async_write_ha_state()


class KEMSAutomaticUpdatesSwitch(_UpdatePolicySwitch):
    """Opt in to unattended KEMS updates."""

    _attr_name = "Automatic updates"
    _attr_icon = "mdi:update"
    policy_key = "automatic_updates"

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, orchestrator, "automatic_updates")


class KEMSAutomaticRestartSwitch(_UpdatePolicySwitch):
    """Permit Home Assistant restarts inside the maintenance window."""

    _attr_name = "Automatic maintenance restart"
    _attr_icon = "mdi:restart-alert"
    policy_key = "automatic_restart"

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, orchestrator, "automatic_maintenance_restart")


class KEMSBackupBeforeUpdateSwitch(_UpdatePolicySwitch):
    """Require an automatic Home Assistant backup before installation."""

    _attr_name = "Backup before update"
    _attr_icon = "mdi:backup-restore"
    policy_key = "backup_before_update"

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, orchestrator, "backup_before_update")


class KEMSUpdateModeSelect(KEMSEntity, SelectEntity):
    """Choose whether safe updates can happen outside the maintenance window."""

    _attr_name = "Update mode"
    _attr_icon = "mdi:calendar-sync"
    _attr_options = list(UPDATE_MODES)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, "update_mode")
        self.orchestrator = orchestrator

    @property
    def current_option(self) -> str:
        return self.orchestrator.policy.mode

    async def async_select_option(self, option: str) -> None:
        if option not in UPDATE_MODES:
            raise HomeAssistantError(f"Unsupported KEMS update mode: {option}")
        await self.orchestrator.async_set_policy(mode=option)
        self.async_write_ha_state()


class _MaintenanceTimeEntity(KEMSEntity, TimeEntity):
    """Base class for the maintenance-window clock controls."""

    _attr_entity_category = EntityCategory.CONFIG
    policy_key = ""

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator, key: str) -> None:
        super().__init__(coordinator, key)
        self.orchestrator = orchestrator

    @property
    def native_value(self) -> time:
        return _parse_clock(str(getattr(self.orchestrator.policy, self.policy_key)))

    async def async_set_value(self, value: time) -> None:
        await self.orchestrator.async_set_policy(
            **{self.policy_key: f"{value.hour:02d}:{value.minute:02d}"}
        )
        self.async_write_ha_state()


class KEMSMaintenanceStartTime(_MaintenanceTimeEntity):
    """Start of the local maintenance window."""

    _attr_name = "Maintenance window start"
    _attr_icon = "mdi:clock-start"
    policy_key = "maintenance_start"

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, orchestrator, "maintenance_window_start")


class KEMSMaintenanceEndTime(_MaintenanceTimeEntity):
    """End of the local maintenance window."""

    _attr_name = "Maintenance window end"
    _attr_icon = "mdi:clock-end"
    policy_key = "maintenance_end"

    def __init__(self, coordinator, orchestrator: KEMSUpdateOrchestrator) -> None:
        super().__init__(coordinator, orchestrator, "maintenance_window_end")
