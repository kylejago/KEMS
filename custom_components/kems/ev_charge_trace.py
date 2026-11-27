"""Persistent read-only event trace for Ohme / FoxESS shared-bus tests.

This recorder consumes KEMS's existing observations. It neither controls the
charger nor changes inverter work mode, power, reserve or tariff settings.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.models import Snapshot
from .kems_core.shared_bus_balance import candidate_extra_slot_house_routing

STORAGE_VERSION = 1
MAX_RECORDS = 960
MAX_EXCEPTION_RECORDS = 64
MAX_COST_BUCKETS = 4320
COST_RETENTION_DAYS = 90
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
    extra_slot_policy: dict[str, Any] | None = None,
    reward_event_active: bool = False,
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
        "extra_slot_cost_sample": extra_slot_cost_sample(
            snapshot, extra_slot_policy, reward_event_active=reward_event_active
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


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def extra_slot_cost_sample(snapshot, policy, *, reward_event_active=False):
    """Conservative, non-authoritative price and power evidence for one scan."""
    if not policy or policy.get("estimated_ev_only_discount_candidate") is not True:
        return {"status": "not_qualified"}
    if (
        reward_event_active
        or snapshot.saving_session_active
        or snapshot.off_peak is not False
        or snapshot.cheap_period_confirmed
        or snapshot.ev_charging is not True
    ):
        return {"status": "other_event_or_tariff"}
    ev = snapshot.ev_power_kw
    grid = snapshot.grid_import_kw
    battery = snapshot.battery_power_kw
    solar = snapshot.solar_power_kw
    export = snapshot.grid_export_kw
    if not all(_finite_number(value) for value in (ev, grid, battery, solar, export)):
        return {"status": "incomplete_power"}
    for field in (
        "grid_import_kw",
        "grid_export_kw",
        "battery_power_kw",
        "solar_power_kw",
    ):
        age = snapshot.source_age_seconds.get(field)
        if (
            field in snapshot.stale_fields
            or not _finite_number(age)
            or not 0 <= age <= 120
        ):
            return {"status": "stale_power"}
    # Require grid supply at least as large as measured EV demand, no material
    # battery discharge, PV or export. This is not independent circuit metering.
    if (
        ev < 0.25
        or grid < ev
        or battery > 0.1
        or not 0 <= solar <= 0.1
        or not 0 <= export <= 0.1
    ):
        return {"status": "ambiguous_grid_allocation"}
    day = snapshot.current_import_rate
    cheap = snapshot.intelligent_slot_evidence.get(
        "effective_fallback_offpeak_rate_pence"
    )
    next_rate = snapshot.next_import_rate
    for field in ("current_import_rate", "next_import_rate", "off_peak"):
        age = snapshot.tariff_source_age_seconds.get(field)
        if (
            field in snapshot.tariff_stale_fields
            or not _finite_number(age)
            or not 0 <= age <= 120
        ):
            return {"status": "stale_tariff"}
    if (
        not all(_finite_number(value) for value in (day, cheap, next_rate))
        or not 0 <= cheap < day
        or abs(next_rate - cheap) > 0.01
    ):
        return {"status": "price_not_corroborated"}
    return {
        "status": "candidate",
        "ev_kw": ev,
        "day_rate_pence": day,
        "estimated_ev_rate_pence": cheap,
        "supplier_discount_confirmed": False,
    }


def extra_slot_interval(left, right):
    """Return a short, qualified UTC half-hour segment or no evidence."""
    a = left.get("extra_slot_cost_sample") or {}
    b = right.get("extra_slot_cost_sample") or {}
    if a.get("status") != "candidate" or b.get("status") != "candidate":
        return None
    if right.get("event") not in ("scan", None):
        return None
    try:
        start = datetime.fromisoformat(left["timestamp"])
        end = datetime.fromisoformat(right["timestamp"])
        if start.tzinfo is None or end.tzinfo is None:
            return None
        elapsed = (end - start).total_seconds()
        if not 0 < elapsed <= 90:
            return None
        slot = int(start.timestamp() // 1800)
        if slot != int(end.timestamp() // 1800):
            return None
        rates = ("day_rate_pence", "estimated_ev_rate_pence")
        if any(a.get(key) != b.get(key) for key in rates):
            return None
        if not all(
            _finite_number(row.get(key))
            for row in (a, b)
            for key in (*rates, "ev_kw")
        ):
            return None
        kwh = min(a["ev_kw"], b["ev_kw"]) * elapsed / 3600
        if kwh <= 0 or not 0 <= a[rates[1]] < a[rates[0]]:
            return None
        return {
            "slot": datetime.fromtimestamp(slot * 1800, UTC).isoformat(),
            "start": start.astimezone(UTC).isoformat(),
            "end": end.astimezone(UTC).isoformat(),
            "covered_seconds": elapsed,
            "estimated_candidate_ev_kwh": kwh,
            "day_rate_comparison_pence": kwh * a[rates[0]],
            "estimated_ev_charge_pence": kwh * a[rates[1]],
        }
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


_COST_TOTAL_FIELDS = (
    "covered_seconds",
    "estimated_candidate_ev_kwh",
    "day_rate_comparison_pence",
    "estimated_ev_charge_pence",
)


def _cost_summary(buckets, records):
    counts = Counter(
        str((row.get("extra_slot_cost_sample") or {}).get("status", "not_recorded"))
        for row in records
    )
    totals = {
        key: sum(row[key] for row in buckets.values()) for key in _COST_TOTAL_FIELDS
    }
    return {
        "scope": "persistent_sampled_ev_only_estimate",
        "sample_status_counts_recent_trace": dict(counts),
        "retained_half_hours": len(buckets),
        "retention_days": COST_RETENTION_DAYS,
        "qualified_sample_interval_seconds": round(totals["covered_seconds"], 3),
        "estimated_candidate_ev_kwh": round(
            totals["estimated_candidate_ev_kwh"], 6
        ),
        "day_rate_comparison_pence": round(totals["day_rate_comparison_pence"], 4),
        "estimated_ev_charge_pence": round(totals["estimated_ev_charge_pence"], 4),
        "estimated_discount_pence": round(
            totals["day_rate_comparison_pence"] - totals["estimated_ev_charge_pence"],
            4,
        ),
        "recent_half_hours": [
            dict(buckets[key]) for key in sorted(buckets)[-64:]
        ],
        "complete_session_energy_verified": False,
        "supplier_discount_confirmed": False,
        "household_tariff_changed": False,
        "roi_or_ledger_write_authorised": False,
    }


def _restore_cost_buckets(payload, *, now):
    """Accept only bounded, nonnegative, internally consistent saved estimates."""
    result = {}
    if not isinstance(payload, dict):
        return result
    for key, row in payload.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            continue
        try:
            start = datetime.fromisoformat(key)
            last_end = datetime.fromisoformat(row["last_end"])
            if (
                start.tzinfo is None
                or last_end.tzinfo is None
                or key != start.astimezone(UTC).isoformat()
                or start.timestamp() % 1800 != 0
                or not now - timedelta(days=COST_RETENTION_DAYS) <= start <= now
                or not start < last_end < start + timedelta(minutes=30)
                or last_end > now
                or not all(
                    _finite_number(row.get(field)) and row[field] >= 0
                    for field in _COST_TOTAL_FIELDS
                )
                or not 0 < row["covered_seconds"] <= 1800
                or row["covered_seconds"] > (last_end - start).total_seconds() + 1e-6
                or row["estimated_candidate_ev_kwh"] <= 0
                or row["estimated_ev_charge_pence"] > row["day_rate_comparison_pence"]
            ):
                continue
        except (TypeError, ValueError, KeyError, OverflowError, OSError):
            continue
        result[key] = {
            "slot": key,
            "last_end": last_end.astimezone(UTC).isoformat(),
            **{field: row[field] for field in _COST_TOTAL_FIELDS},
        }
    return {key: result[key] for key in sorted(result)[-MAX_COST_BUCKETS:]}


def _append_cost_segment(buckets, segment):
    """Accumulate disjoint evidence only, even across repeated timestamps."""
    key = segment["slot"]
    prior = buckets.get(key)
    if prior is not None and segment["start"] < prior["last_end"]:
        return False
    new = {
        "slot": key,
        "last_end": segment["end"],
        **{
            field: segment[field] + (prior[field] if prior else 0.0)
            for field in _COST_TOTAL_FIELDS
        },
    }
    if new["covered_seconds"] > 1800:
        return False
    buckets[key] = new
    return True


def summarise_extra_slot_cost(records):
    """Pure short-trace estimate helper for deterministic regression tests."""
    buckets = {}
    for left, right in zip(records, records[1:]):
        segment = extra_slot_interval(left, right)
        if segment is not None:
            _append_cost_segment(buckets, segment)
    return _cost_summary(buckets, records)


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
        self._cost_buckets: dict[str, Any] = {}
        self._cost_previous: dict[str, Any] | None = None

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
            "extra_slot_cost_evidence": _cost_summary(
                self._cost_buckets, self._records
            ),
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
        self._cost_buckets = _restore_cost_buckets(
            data.get("extra_slot_cost_buckets"), now=datetime.now(UTC)
        )
        # Never bridge a restart using a previously persisted sample.
        self._cost_previous = None
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
        extra_slot_policy: dict[str, Any] | None = None,
        reward_event_active: bool = False,
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
            extra_slot_policy=extra_slot_policy,
            reward_event_active=reward_event_active,
        )
        cost_changed = False
        if self._cost_previous is not None:
            segment = extra_slot_interval(self._cost_previous, sample)
            if segment is not None:
                new_slot = segment["slot"] not in self._cost_buckets
                cost_changed = _append_cost_segment(self._cost_buckets, segment)
                if cost_changed and new_slot:
                    # Existing buckets already passed restore/append checks.
                    # Prune once per new half-hour rather than every scan.
                    cutoff = (
                        now.astimezone(UTC) - timedelta(days=COST_RETENTION_DAYS)
                    ).isoformat()
                    self._cost_buckets = {
                        key: self._cost_buckets[key]
                        for key in sorted(self._cost_buckets)[-MAX_COST_BUCKETS:]
                        if key >= cutoff
                    }
        self._cost_previous = sample
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
        if cost_changed and not (due or transition):
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
                "extra_slot_cost_buckets": self._cost_buckets,
            }
        )
        self._unsaved = 0
