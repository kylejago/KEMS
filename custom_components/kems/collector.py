"""Collect observations from KEMS providers."""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from .kems_core import Snapshot
from .providers.foxess import FoxESSProvider
from .providers.gas import GasProvider
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider


class Collector:
    """Collect read-only data from all configured providers."""

    def __init__(
        self,
        octopus: OctopusProvider,
        gas: GasProvider,
        ohme: OhmeProvider,
        foxess: FoxESSProvider,
    ) -> None:
        """Initialise the collector."""
        self._octopus = octopus
        self._gas = gas
        self._ohme = ohme
        self._foxess = foxess

    def collect(self) -> Snapshot:
        """Create a complete whole-home monitoring snapshot."""
        octopus = self._octopus.get_state()
        gas = self._gas.get_state()
        ohme = self._ohme.get_state()
        foxess = self._foxess.get_state()

        return Snapshot(
            timestamp=dt_util.now(),
            current_import_rate=octopus.current_import_rate,
            next_import_rate=octopus.next_import_rate,
            current_export_rate=octopus.current_export_rate,
            electricity_standing_charge=octopus.electricity_standing_charge,
            off_peak=octopus.off_peak,
            intelligent_slot=octopus.intelligent_slot,
            next_offpeak_start=octopus.next_offpeak_start,
            offpeak_end=octopus.offpeak_end,
            gas_current_rate=gas.current_rate,
            gas_standing_charge=gas.standing_charge,
            gas_meter_total_kwh=gas.meter_total_kwh,
            gas_usage_today_kwh=gas.usage_today_kwh,
            gas_cost_today_pence=gas.cost_today_pence,
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
            raw_grid_import_kw=foxess.raw_grid_import_kw,
            raw_grid_export_kw=foxess.raw_grid_export_kw,
            grid_flow_mode=foxess.grid_flow_mode,
        )
