"""Collect data from providers."""

from __future__ import annotations

from kems_core.snapshot import Snapshot

from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider


class Collector:
    """Collect data from all providers."""

    def __init__(
        self,
        octopus: OctopusProvider,
        ohme: OhmeProvider,
    ) -> None:
        self._octopus = octopus
        self._ohme = ohme

    def collect(self) -> Snapshot:
        """Create a monitoring snapshot."""

        snapshot = Snapshot()

        octopus = self._octopus.get_state()
        ohme = self._ohme.get_state()

        snapshot.electricity_rate = octopus.current_rate
        snapshot.cheap_rate = octopus.off_peak

        snapshot.ev_connected = ohme.connected
        snapshot.ev_charging = ohme.charging
        snapshot.ev_power_kw = ohme.power_kw
        snapshot.ev_soc = ohme.vehicle_soc

        return snapshot
