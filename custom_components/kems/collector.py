"""Collect observations from KEMS providers."""

from __future__ import annotations

from .kems_core.snapshot import Snapshot
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider


class Collector:
    """Collect read-only data from all configured providers."""

    def __init__(
        self,
        octopus: OctopusProvider,
        ohme: OhmeProvider,
    ) -> None:
        """Initialise the collector."""
        self._octopus = octopus
        self._ohme = ohme

    def collect(self) -> Snapshot:
        """Create a complete monitoring snapshot."""
        octopus = self._octopus.get_state()
        ohme = self._ohme.get_state()

        return Snapshot(
            current_import_rate=octopus.current_rate_pence,
            next_import_rate=octopus.next_rate_pence,
            off_peak=octopus.off_peak,
            intelligent_slot=octopus.intelligent_slot,
            next_offpeak_start=octopus.next_offpeak_start,
            offpeak_end=octopus.offpeak_end,
            ev_connected=ohme.connected,
            ev_charging=ohme.charging,
            ev_power_kw=ohme.power_kw,
            ev_soc=ohme.vehicle_soc,
        )
