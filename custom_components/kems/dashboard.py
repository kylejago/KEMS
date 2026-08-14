"""KEMS-managed Home Assistant dashboard synchronisation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

MANAGED_DASHBOARD_FILENAME = "kems_master_dashboard.yaml"
PACKAGED_DASHBOARD_PATH = Path(__file__).with_name(MANAGED_DASHBOARD_FILENAME)


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


async def async_sync_managed_dashboard(hass: HomeAssistant) -> bool:
    """Synchronise the shipped KEMS dashboard into the HA config directory."""
    target = Path(hass.config.path(MANAGED_DASHBOARD_FILENAME))
    changed = await hass.async_add_executor_job(
        _sync_dashboard_file,
        PACKAGED_DASHBOARD_PATH,
        target,
    )
    if changed:
        LOGGER.info("Updated managed KEMS dashboard at %s", target)
    return changed
