"""Collect data from providers."""

from __future__ import annotations

from .kems_core.snapshot import Snapshot
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider


class Collector:
    """Collect data from all providers."""

    def __init__(
        self,
        octopus: OctopusProvider,
        ohme: OhmeProvider,
    ) -> None:
        """Initialise the collector."""
        self._octopus = octopus
        self._ohme = ohme

    def collect(self) -> Snapshot:
        """Create a monitoring snapshot."""

        snapshot = Snapshot()

        # Octopus
        octopus = self._octopus.get_state()

        snapshot.current_import_rate = octopus.current_rate
        snapshot.next_import_rate = octopus.next_rate

        snapshot.off_peak = octopus.off_peak
        snapshot.intelligent_slot = octopus.intelligent_slot

        snapshot.next_offpeak_start = octopus.next_offpeak_start
        snapshot.offpeak_end = octopus.offpeak_end

        # Ohme
        ohme = self._ohme.get_state()

        snapshot.ev_connected = ohme.connected
        snapshot.ev_charging = ohme.charging
        snapshot.ev_power_kw = ohme.power_kw
        snapshot.ev_soc = ohme.vehicle_soc

        return snapshot
