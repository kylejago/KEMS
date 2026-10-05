"""Persistent read-only event trace for Ohme / FoxESS shared-bus tests.

This recorder consumes KEMS's existing observations. It neither controls the
charger nor changes inverter work mode, power, reserve or tariff settings.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.models import Snapshot

STORAGE_VERSION = 1
MAX_RECORDS = 960
RETENTION_HOURS = 72
PRELUDE_MINUTES = 15
POSTLUDE_MINUTES = 15
SAVE_EVERY = 3
MIN_INTERVAL_SECONDS = 45
_READBACK_KEYS = (
    "work_mode",
    "force_charge_power",
    "force_discharge_power",
    "min_soc_on_grid",
    "export_power_limit",
)



def infer_pre_hold_min_soc_baseline(
    samples: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    contaminated_min_soc_on_grid: float | None,
    tolerance: float = 0.05,
) -> float | None:
    """Recover a pre-hold MinSOC only from one retained KEMS-owned EV session.

    Alpha9.82 uses the read-only event trace as an upgrade bridge when Alpha9.80
    has already cleared the backend's last-verified hold evidence during unload.
    A candidate is accepted only when the same retained session proves:
    - a transition into a confirmed cheap period while the EV is connected;
    - KEMS-owned Self Use at the elevated contaminated MinSOC during that cheap
      period; and
    - an earlier KEMS-owned non-cheap Self Use readback at a lower MinSOC.

    The trace already has a bounded 72-hour retention window. No trace evidence
    means no repair.
    """
    try:
        contaminated = float(contaminated_min_soc_on_grid)
    except (TypeError, ValueError):
        return None
    if not isfinite(contaminated) or not 0.0 <= contaminated <= 100.0:
        return None

    def _readback(sample: dict[str, Any]) -> float | None:
        foxess = sample.get("foxess_readback")
        if not isinstance(foxess, dict):
            return None
        item = foxess.get("min_soc_on_grid")
        if not isinstance(item, dict):
            return None
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            return None
        return value if isfinite(value) and 0.0 <= value <= 100.0 else None

    def _owned_self_use(sample: dict[str, Any]) -> bool:
        control = sample.get("existing_live_control")
        return bool(
            isinstance(control, dict)
            and control.get("owned_by_kems") is True
            and control.get("decision_action") == "self_use"
        )

    records = [sample for sample in samples if isinstance(sample, dict)]
    for start_index in range(len(records) - 1, -1, -1):
        start = records[start_index]
        if not (
            start.get("event") == "cheap_slot_transition"
            and start.get("cheap_period_confirmed") is True
            and start.get("ev_connected") is True
        ):
            continue

        elevated_hold_proven = False
        for held in records[start_index:]:
            if held.get("cheap_period_confirmed") is not True:
                if elevated_hold_proven:
                    break
                continue
            value = _readback(held)
            if (
                held.get("ev_connected") is True
                and _owned_self_use(held)
                and value is not None
                and abs(value - contaminated) <= tolerance
            ):
                elevated_hold_proven = True
                break
        if not elevated_hold_proven:
            continue

        for previous in reversed(records[:start_index]):
            if previous.get("cheap_period_confirmed") is True:
                break
            value = _readback(previous)
            if (
                previous.get("ev_connected") is True
                and _owned_self_use(previous)
                and value is not None
                and value + tolerance < contaminated
            ):
                return round(value, 1)
        return None
    return None


def build_ev_trace_sample(
    snapshot: Snapshot,
    *,
    event: str,
    foxess_control: dict[str, Any] | None = None,
    command_shadow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one compact observation, with labelled *observed* readbacks."""
    command_shadow = command_shadow or {}
    binding = command_shadow.get("entity_binding") or {}
    entities = binding.get("entities") or {}
    readbacks = {
        key: {
            "value": entities[key].get("normalised_observation"),
            "source": entities[key].get("observation_source"),
            "status": entities[key].get("status"),
        }
        for key in _READBACK_KEYS
        if isinstance(entities.get(key), dict)
    }
    control = foxess_control or {}
    return {
        "timestamp": snapshot.timestamp.isoformat(),
        "event": event,
        "ev_connected": snapshot.ev_connected,
        "ev_charging": snapshot.ev_charging,
        "ev_power_kw": snapshot.ev_power_kw,
        "ev_power_age_seconds": snapshot.ev_power_age_seconds,
        "ev_load_in_house_load": snapshot.ev_load_in_house_load,
        "house_load_kw": snapshot.house_load_kw,
        "solar_power_kw": snapshot.solar_power_kw,
        "battery_power_kw": snapshot.battery_power_kw,
        "battery_soc": snapshot.battery_soc,
        "grid_import_kw": snapshot.grid_import_kw,
        "grid_export_kw": snapshot.grid_export_kw,
        "off_peak": snapshot.off_peak,
        "intelligent_slot": snapshot.intelligent_slot,
        "cheap_period_confirmed": snapshot.cheap_period_confirmed,
        "offpeak_end": (
            snapshot.offpeak_end.isoformat()
            if snapshot.offpeak_end is not None
            else None
        ),
        "next_offpeak_start": (
            snapshot.next_offpeak_start.isoformat()
            if snapshot.next_offpeak_start is not None
            else None
        ),
        "intelligent_slot_confirmation": snapshot.intelligent_slot_confirmation,
        "saving_session_active": snapshot.saving_session_active,
        "source_data_age_seconds": snapshot.source_data_age_seconds,
        "tariff_source_data_age_seconds": snapshot.tariff_source_data_age_seconds,
        "source_age_seconds": dict(snapshot.source_age_seconds),
        "stale_fields": list(snapshot.stale_fields),
        "tariff_source_age_seconds": dict(snapshot.tariff_source_age_seconds),
        "tariff_stale_fields": list(snapshot.tariff_stale_fields),
        "shared_bus_audit": dict(snapshot.shared_bus_ev_audit),
        "binding_status": binding.get("status"),
        "foxess_readback": readbacks,
        "existing_live_control": {
            "decision_action": control.get("decision_action"),
            "commands_permitted": control.get("commands_permitted"),
            "owned_by_kems": control.get("owned_by_kems"),
            "writes_this_cycle": list(control.get("writes_this_cycle") or ()),
            "last_write_at": control.get("last_write_at"),
            "last_write_result": control.get("last_write_result"),
        },
        "new_ev_routing_hardware_authorised": False,
    }


class EVChargeTraceRecorder:
    """Keep prelude, charging and stop samples without changing hardware."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.ev_trace"
        )
        self._records: list[dict[str, Any]] = []
        self._prelude: list[dict[str, Any]] = []
        self._previous_connected = False
        self._previous_charging = False
        self._previous_cheap = False
        self._post_until: datetime | None = None
        self._unsaved = 0

    @property
    def state(self) -> dict[str, Any]:
        """Expose a bounded, non-secret passive evidence pack."""
        return {
            "scope": "read_only_existing_kems_sources",
            "sample_count": len(self._records),
            "samples": list(self._records),
            "new_ev_routing_hardware_authorised": False,
            "sampling_note": (
                "At coordinator scan cadence while plugged/charging and 15 "
                "minutes after disconnect; source reports are not atomic"
            ),
        }

    def wants_capture(self, snapshot: Snapshot) -> bool:
        """Avoid FoxESS binding lookups on unrelated idle scans."""
        return bool(
            snapshot.ev_connected is True
            or snapshot.ev_charging is True
            or (snapshot.ev_power_kw or 0.0) > 0.1
            or self._previous_connected
            or self._previous_charging
            or (self._post_until is not None and snapshot.timestamp <= self._post_until)
        )

    async def async_load(self) -> None:
        """Recover retained evidence across Home Assistant restart."""
        data = await self._store.async_load() or {}
        self._records = [
            item for item in data.get("records", []) if isinstance(item, dict)
        ][-MAX_RECORDS:]
        if self._records:
            last = self._records[-1]
            self._previous_connected = last.get("ev_connected") is True
            self._previous_charging = last.get("ev_charging") is True
            self._previous_cheap = last.get("cheap_period_confirmed") is True

    async def async_record(
        self,
        snapshot: Snapshot,
        *,
        foxess_control: dict[str, Any] | None = None,
        command_shadow: dict[str, Any] | None = None,
    ) -> bool:
        """Record actual scan data; save transitions immediately."""
        now = snapshot.timestamp
        connected = snapshot.ev_connected is True
        charging = snapshot.ev_charging is True
        cheap = snapshot.cheap_period_confirmed
        active = connected or charging or (snapshot.ev_power_kw or 0.0) > 0.1
        started = charging and not self._previous_charging
        stopped = self._previous_charging and not charging
        plugged = connected and not self._previous_connected
        unplugged = self._previous_connected and not connected
        cheap_changed = cheap != self._previous_cheap
        if started:
            event = "charge_start"
        elif stopped:
            event = "charge_stop"
        elif plugged:
            event = "plugged"
        elif unplugged:
            event = "unplugged"
        elif cheap_changed and (active or self._previous_connected):
            event = "cheap_slot_transition"
        else:
            event = "scan"
        sample = build_ev_trace_sample(
            snapshot,
            event=event,
            foxess_control=foxess_control,
            command_shadow=command_shadow,
        )
        if not self.wants_capture(snapshot):
            self._prelude.append(sample)
            cutoff = now - timedelta(minutes=PRELUDE_MINUTES)
            self._prelude = [
                item
                for item in self._prelude
                if datetime.fromisoformat(item["timestamp"]) >= cutoff
            ][-32:]
            return False

        if active and not self._previous_connected and not self._previous_charging:
            self._records.extend(self._prelude)
            self._prelude.clear()
        if unplugged:
            self._post_until = now + timedelta(minutes=POSTLUDE_MINUTES)
        due = not self._records or (
            now - datetime.fromisoformat(self._records[-1]["timestamp"])
        ) >= timedelta(seconds=MIN_INTERVAL_SECONDS)
        transition = event != "scan"
        if due or transition:
            self._records.append(sample)
            cutoff = now - timedelta(hours=RETENTION_HOURS)
            self._records = [
                item
                for item in self._records
                if datetime.fromisoformat(item["timestamp"]) >= cutoff
            ][-MAX_RECORDS:]
            self._unsaved += 1
        self._previous_connected = connected
        self._previous_charging = charging
        self._previous_cheap = cheap
        if transition or self._unsaved >= SAVE_EVERY:
            await self.async_save()
        return bool(due or transition)

    async def async_save(self) -> None:
        """Persist the bounded trace; never write to FoxESS/Ohme."""
        await self._store.async_save({"records": self._records})
        self._unsaved = 0
