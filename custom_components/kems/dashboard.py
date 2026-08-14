"""KEMS-managed Home Assistant dashboard and ESPHome asset synchronisation."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from aiohttp import ClientError, WSMsgType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

LOGGER = logging.getLogger(__name__)

MANAGED_DASHBOARD_FILENAME = "kems_master_dashboard.yaml"
PACKAGED_DASHBOARD_PATH = Path(__file__).with_name(MANAGED_DASHBOARD_FILENAME)

MANAGED_PANEL_FILENAME = "kems16x16.yaml"
MANAGED_PANEL_HEADER = b"# KEMS-MANAGED-ESPHOME-PANEL"
PACKAGED_PANEL_PATH = Path(__file__).with_name(MANAGED_PANEL_FILENAME)

SUPERVISOR_BASE_URL = "http://supervisor"
ESPHOME_ADDON_SLUGS = (
    "5c53de3b_esphome",
    "5c53de3b_esphome-beta",
    "5c53de3b_esphome-dev",
)
PANEL_AUTO_OTA_RETRY_DELAYS = (5, 15, 30)


class PanelAutoOTAError(RuntimeError):
    """Raised when KEMS cannot queue the managed ESPHome panel install."""


def _sync_dashboard_file(source: Path, target: Path) -> bool:
    """Copy the packaged dashboard atomically when its contents changed."""
    source_bytes = source.read_bytes()
    if target.exists() and target.read_bytes() == source_bytes:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(source_bytes)
    os.replace(temporary, target)
    return True


def _panel_is_kems_managed(target: Path) -> bool:
    """Return whether the existing panel has already adopted KEMS management."""
    if not target.exists():
        return False
    try:
        return target.read_bytes().startswith(MANAGED_PANEL_HEADER)
    except OSError:
        return False


def _sync_existing_panel_file(source: Path, target: Path) -> bool:
    """Refresh an opted-in KEMS panel config without creating one for everyone."""
    if not target.exists():
        return False

    source_bytes = source.read_bytes()
    if target.read_bytes() == source_bytes:
        return False

    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(source_bytes)
    os.replace(temporary, target)
    return True


def _supervisor_data(payload: Any) -> dict[str, Any]:
    """Return the data object from a Supervisor API response."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


async def _async_esphome_ingress_port(hass: HomeAssistant) -> int:
    """Discover the trusted ESPHome Device Builder ingress port."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise PanelAutoOTAError(
            "Home Assistant Supervisor is unavailable; automatic panel OTA requires "
            "Home Assistant OS or Supervised with ESPHome Device Builder"
        )

    session = async_get_clientsession(hass)
    headers = {"Authorization": f"Bearer {token}"}

    for slug in ESPHOME_ADDON_SLUGS:
        url = f"{SUPERVISOR_BASE_URL}/addons/{slug}/info"
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 404:
                    continue
                if response.status != 200:
                    raise PanelAutoOTAError(
                        f"Supervisor returned HTTP {response.status} for {slug}"
                    )
                info = _supervisor_data(await response.json())
        except ClientError as err:
            raise PanelAutoOTAError(
                f"Unable to query Home Assistant Supervisor: {err}"
            ) from err

        if info.get("state") != "started":
            raise PanelAutoOTAError("ESPHome Device Builder is installed but not started")

        ingress_port = info.get("ingress_port")
        if isinstance(ingress_port, int) and ingress_port > 0:
            return ingress_port

        raise PanelAutoOTAError(
            "ESPHome Device Builder does not expose a trusted ingress port"
        )

    raise PanelAutoOTAError("ESPHome Device Builder add-on was not found")


async def _async_queue_esphome_install(hass: HomeAssistant, ingress_port: int) -> str:
    """Queue compile plus OTA upload in ESPHome Device Builder."""
    session = async_get_clientsession(hass)
    websocket_url = f"ws://127.0.0.1:{ingress_port}/ws"
    message_id = "kems-managed-panel-auto-ota"

    try:
        async with session.ws_connect(websocket_url, heartbeat=30) as websocket:
            hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
            if isinstance(hello, dict) and hello.get("requires_auth") is True:
                raise PanelAutoOTAError(
                    "ESPHome trusted ingress unexpectedly requested authentication"
                )

            await websocket.send_json(
                {
                    "command": "firmware/install",
                    "message_id": message_id,
                    "args": {
                        "configuration": MANAGED_PANEL_FILENAME,
                        "port": "OTA",
                    },
                }
            )

            while True:
                message = await asyncio.wait_for(websocket.receive(), timeout=15)
                if message.type == WSMsgType.TEXT:
                    payload = message.json()
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("message_id") != message_id:
                        continue
                    if "error" in payload:
                        raise PanelAutoOTAError(
                            f"ESPHome rejected automatic install: {payload['error']}"
                        )
                    result = payload.get("result")
                    if not isinstance(result, dict):
                        raise PanelAutoOTAError(
                            "ESPHome returned an invalid firmware/install response"
                        )
                    job_id = result.get("job_id")
                    return str(job_id or "queued")

                if message.type in {
                    WSMsgType.CLOSE,
                    WSMsgType.CLOSED,
                    WSMsgType.ERROR,
                }:
                    raise PanelAutoOTAError(
                        "ESPHome Device Builder closed the connection before queuing "
                        "the panel install"
                    )
    except (ClientError, asyncio.TimeoutError) as err:
        raise PanelAutoOTAError(
            f"Unable to reach ESPHome Device Builder: {err}"
        ) from err


async def async_auto_install_managed_panel(hass: HomeAssistant) -> None:
    """Queue a managed panel compile and wireless install with startup retries."""
    last_error: Exception | None = None

    for delay in PANEL_AUTO_OTA_RETRY_DELAYS:
        await asyncio.sleep(delay)
        try:
            ingress_port = await _async_esphome_ingress_port(hass)
            job_id = await _async_queue_esphome_install(hass, ingress_port)
        except PanelAutoOTAError as err:
            last_error = err
            LOGGER.warning(
                "KEMS automatic 16x16 panel OTA attempt failed; will retry if "
                "startup time remains: %s",
                err,
            )
            continue

        LOGGER.warning(
            "KEMS queued automatic ESPHome compile and OTA install for %s "
            "(job %s)",
            MANAGED_PANEL_FILENAME,
            job_id,
        )
        return

    LOGGER.error(
        "KEMS updated %s but could not queue its automatic ESPHome OTA install: %s",
        MANAGED_PANEL_FILENAME,
        last_error or "unknown error",
    )


async def async_sync_managed_dashboard(hass: HomeAssistant) -> bool:
    """Synchronise the shipped dashboard and any opted-in KEMS panel config."""
    dashboard_target = Path(hass.config.path(MANAGED_DASHBOARD_FILENAME))
    dashboard_changed = await hass.async_add_executor_job(
        _sync_dashboard_file,
        PACKAGED_DASHBOARD_PATH,
        dashboard_target,
    )
    if dashboard_changed:
        LOGGER.info("Updated managed KEMS dashboard at %s", dashboard_target)

    panel_target = Path(hass.config.path("esphome", MANAGED_PANEL_FILENAME))
    panel_was_managed = await hass.async_add_executor_job(
        _panel_is_kems_managed,
        panel_target,
    )
    try:
        panel_changed = await hass.async_add_executor_job(
            _sync_existing_panel_file,
            PACKAGED_PANEL_PATH,
            panel_target,
        )
    except OSError:
        LOGGER.exception(
            "Unable to update managed KEMS 16x16 panel at %s", panel_target
        )
        panel_changed = False

    if panel_changed and panel_was_managed:
        LOGGER.warning(
            "Updated managed KEMS 16x16 ESPHome config at %s; queuing automatic "
            "compile and wireless install",
            panel_target,
        )
        hass.async_create_task(
            async_auto_install_managed_panel(hass),
            "KEMS managed 16x16 panel automatic OTA",
        )
    elif panel_changed:
        LOGGER.warning(
            "Updated KEMS 16x16 ESPHome config at %s. This is its first managed "
            "adoption, so install it wirelessly once in ESPHome; subsequent managed "
            "changes will install automatically.",
            panel_target,
        )

    return dashboard_changed or panel_changed
