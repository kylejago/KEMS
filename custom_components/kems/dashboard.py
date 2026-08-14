"""KEMS-managed Home Assistant dashboard and ESPHome asset synchronisation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

MANAGED_DASHBOARD_FILENAME = "kems_master_dashboard.yaml"
PACKAGED_DASHBOARD_PATH = Path(__file__).with_name(MANAGED_DASHBOARD_FILENAME)

MANAGED_PANEL_FILENAME = "kems16x16.yaml"
PACKAGED_PANEL_PATH = Path(__file__).with_name(MANAGED_PANEL_FILENAME)


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

    if panel_changed:
        LOGGER.warning(
            "Updated managed KEMS 16x16 ESPHome config at %s; "
            "compile/install kems16x16 in ESPHome to flash the new firmware",
            panel_target,
        )

    return dashboard_changed or panel_changed
