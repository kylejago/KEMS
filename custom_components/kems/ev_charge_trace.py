"""Persistent read-only event trace for Ohme / FoxESS shared-bus tests.

This recorder consumes KEMS's existing observations. It neither controls the
charger nor changes inverter work mode, power, reserve or tariff settings.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.models import Snapshot
from .kems_core.shared_bus_balance import candidate_extra_slot_house_routing

STORAGE_VERSION = 1
MAX_RECORDS = 960
MAX_EXCEPTION_RECORDS = 64
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


def build_ev_trace_sample(
    snapshot: Snapshot,
    *,
    event: str,
    foxess_control: dict[str, Any] | None = None,
    command_shadow: dict[str, Any] | None = None,
    planned_control: Any = None,
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
    confirmed_ev_cheap = bool(
        snapshot.cheap_period_confirmed
        and (snapshot.ev_charging is True or (snapshot.ev_power_kw or 0.0) > 0.25)
    )
    charge_target = getattr(planned_control, "desired_charge_power_kw", None)
    charging_audit = {
        "confirmed_cheap_ev_charging": confirmed_ev_cheap,
        "desired_battery_charge_power_kw": charge_target,
        "ev_grid_guard_status": getattr(planned_control, "ev_grid_guard_status", None),
        "site_import_limit_kw": getattr(planned_control, "site_import_limit_kw", None),
        "site_import_headroom_kw": getattr(
            planned_control, "site_import_headroom_kw", None
        ),
        "charge_cap_kw_when_ev_charging": 5.0 if confirmed_ev_cheap else None,
        "cap_target_exceeded": bool(
            confirmed_ev_cheap
            and isinstance(charge_target, (int, float))
            and charge_target > 5.001
        ),
        "battery_discharging_during_ev_charge": bool(
            confirmed_ev_cheap
            and snapshot.battery_power_kw is not None
            and snapshot.battery_power_kw > 0.3
        ),
        "source_note": (
            "KEMS desired target and time-aligned sampled physical power; "
            "not proof of independent EV circuit isolation or the actual "
            "FoxESS charge-power setpoint readback."
        ),
        "reporting_only": True,
    }
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
        "ev_cheap_charge_cap_audit": charging_audit,
        "outside_cheap_ev_startup_risk": bool(
            not snapshot.cheap_period_confirmed
            and snapshot.ev_charging is True
            and snapshot.ev_power_kw is not None
            and snapshot.grid_import_kw is not None
            and snapshot.battery_power_kw is not None
            and snapshot.ev_power_kw - snapshot.grid_import_kw > 0.3
            and snapshot.battery_power_kw > 0.3
        ),
        "extra_slot_house_routing_candidate": candidate_extra_slot_house_routing(
            snapshot,
            site_import_limit_kw=getattr(planned_control, "site_import_limit_kw", None),
        ),
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


def _is_ev_trace_exception(row: dict[str, Any]) -> bool:
    audit = row.get("ev_cheap_charge_cap_audit")
    return row.get("outside_cheap_ev_startup_risk") is True or (
        isinstance(audit, dict)
        and (
            audit.get("battery_discharging_during_ev_charge") is True
            or audit.get("cap_target_exceeded") is True
        )
    )


def _discharge_exception_context(records):
    """Attribute sample context without inferring duration or cause."""
    actions = Counter()
    modes = Counter()
    writes_after_sample = 0
    samples = 0
    for row in records:
        audit = row.get("ev_cheap_charge_cap_audit")
        if not isinstance(audit, dict) or not audit.get(
            "battery_discharging_during_ev_charge"
        ):
            continue
        samples += 1
        control = row.get("existing_live_control") or {}
        readback = row.get("foxess_readback") or {}
        mode = readback.get("work_mode") or {}
        actions[str(control.get("decision_action"))] += 1
        modes[str(mode.get("value"))] += 1
        try:
            sampled = datetime.fromisoformat(row["timestamp"])
            written = datetime.fromisoformat(control["last_write_at"])
            if sampled.tzinfo is not None and written.tzinfo is not None:
                writes_after_sample += written > sampled
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "samples": samples,
        "control_action_counts": dict(actions),
        "work_mode_readback_counts": dict(modes),
        "command_written_after_physical_sample": writes_after_sample,
        "persistent_discharge_proven": False,
        "hardware_write_authorised": False,
    }


class EVChargeTraceRecorder:
    """Keep prelude, charging and stop samples without changing hardware."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.ev_trace"
        )
        self._records: list[dict[str, Any]] = []
        self._exception_records: list[dict[str, Any]] = []
        self._prelude: list[dict[str, Any]] = []
        self._previous_connected = False
        self._previous_charging = False
        self._previous_cheap = False
        self._post_until: datetime | None = None
        self._unsaved = 0

    @property
    def state(self) -> dict[str, Any]:
        """Expose bounded evidence and a compact EV charge-cap audit."""
        audits = [
            row["ev_cheap_charge_cap_audit"]
            for row in self._records
            if isinstance(row.get("ev_cheap_charge_cap_audit"), dict)
            and row["ev_cheap_charge_cap_audit"].get("confirmed_cheap_ev_charging")
            is True
        ]
        discharge_events = sum(
            item.get("battery_discharging_during_ev_charge") is True for item in audits
        )
        cap_exceedances = sum(
            item.get("cap_target_exceeded") is True for item in audits
        )
        daytime = [
            row
            for row in self._records
            if row.get("ev_charging") is True
            and row.get("cheap_period_confirmed") is False
            and row.get("saving_session_active") is False
        ]
        candidates = [
            item
            for row in daytime
            if isinstance(item := row.get("extra_slot_house_routing_candidate"), dict)
        ]
        return {
            "extra_slot_routing_readiness": {
                "outside_confirmed_cheap_charging_samples": len(daytime),
                "candidate_status_counts": dict(
                    Counter(str(item.get("status")) for item in candidates)
                ),
                "fallback_reason_counts": dict(
                    Counter(
                        str(item.get("reason"))
                        for item in candidates
                        if item.get("status") == "hold_fallback_required"
                    )
                ),
                "candidate_is_not_supplier_discount_proof": True,
                "hardware_write_authorised": False,
            },
            "discharge_exception_context": _discharge_exception_context(
                self._exception_records
            ),
            "scope": "read_only_existing_kems_sources",
            "sample_count": len(self._records),
            "samples": list(self._records),
            "exception_samples": list(self._exception_records),
            "exception_sample_limit": MAX_EXCEPTION_RECORDS,
            "exception_scope": "observed_samples_not_continuous_duration",
            "outside_cheap_ev_risk_samples_retained": sum(
                row.get("outside_cheap_ev_startup_risk") is True
                for row in self._exception_records
            ),
            "outside_cheap_risk_note": (
                "Potential shared-bus battery contribution; non-atomic reports "
                "and solar may explain differences. Not tariff or isolation proof."
            ),
            "ev_cheap_charge_cap_summary": {
                "status": (
                    "not_yet_observed"
                    if not audits
                    else (
                        "unexpected_battery_discharge_observed"
                        if discharge_events
                        else "observations_recorded"
                    )
                ),
                "confirmed_cheap_ev_samples": len(audits),
                "unexpected_battery_discharge_samples": discharge_events,
                "charge_target_above_5kw_samples": cap_exceedances,
                "samples_missing_planned_target": sum(
                    item.get("desired_battery_charge_power_kw") is None
                    for item in audits
                ),
                "independent_ev_isolation_proven": False,
                "reporting_only": True,
            },
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
        # Migrate retained observations from older storage without changing its
        # schema version. A separate bounded tail survives normal trace rollover.
        exceptions = [
            row
            for row in (*(data.get("exception_records") or []), *self._records)
            if isinstance(row, dict)
            and isinstance(row.get("timestamp"), str)
            and _is_ev_trace_exception(row)
        ]
        by_timestamp = {row["timestamp"]: row for row in exceptions}
        self._exception_records = sorted(
            by_timestamp.values(), key=lambda row: row["timestamp"]
        )[-MAX_EXCEPTION_RECORDS:]
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
        planned_control: Any = None,
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
            planned_control=planned_control,
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
        exception = _is_ev_trace_exception(sample)
        if due or transition:
            self._records.append(sample)
            if exception:
                self._exception_records.append(sample)
                self._exception_records = self._exception_records[
                    -MAX_EXCEPTION_RECORDS:
                ]
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
        if transition or (due and exception) or self._unsaved >= SAVE_EVERY:
            await self.async_save()
        return bool(due or transition)

    async def async_save(self) -> None:
        """Persist the bounded trace; never write to FoxESS/Ohme."""
        await self._store.async_save(
            {
                "records": self._records,
                "exception_records": self._exception_records,
            }
        )
        self._unsaved = 0
