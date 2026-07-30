"""Collect observations from KEMS providers."""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from .kems_core import Snapshot
from .providers.foxess import FoxESSProvider
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider


class Collector:
    """Collect read-only data from all configured providers."""

    def __init__(
        self,
        octopus: OctopusProvider,
        ohme: OhmeProvider,
        foxess: FoxESSProvider,
    ) -> None:
        """Initialise the collector."""
        self._octopus = octopus
        self._ohme = ohme
        self._foxess = foxess

    def collect(self) -> Snapshot:
        """Create a complete monitoring snapshot."""
        octopus = self._octopus.get_state()
        ohme = self._ohme.get_state()
        foxess = self._foxess.get_state()

        return Snapshot(
            timestamp=dt_util.now(),
            current_import_rate=octopus.current_import_rate,
            next_import_rate=octopus.next_import_rate,
            current_export_rate=octopus.current_export_rate,
            off_peak=octopus.off_peak,
            intelligent_slot=octopus.intelligent_slot,
            next_offpeak_start=octopus.next_offpeak_start,
            offpeak_end=octopus.offpeak_end,
            ev_connected=ohme.connected,
            ev_charging=ohme.charging,
            ev_power_kw=ohme.power_kw,
            ev_soc=ohme.vehicle_soc,
            house_load_kw=foxess.house_load_kw,
            battery_soc=foxess.battery_soc,
            battery_power_kw=foxess.battery_power_kw,
            solar_power_kw=foxess.solar_power_kw,
            grid_import_kw=foxess.grid_import_kw,
            grid_export_kw=foxess.grid_export_kw,
        )
