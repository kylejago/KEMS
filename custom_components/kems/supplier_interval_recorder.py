"""Local supplier interval intake; no account API, services or control writes."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.supplier_charges import (
    CHARGE_FORMAT,
    SupplierChargeEvidence,
    baseline_capture_diagnostic,
    capture_completed_baseline,
    capture_joined_baseline,
    completed_power_down_estimate,
    merge_completed_baseline,
    supplier_cost_rows,
)
from .kems_core.supplier_intervals import (
    FORMAT,
    KINDS,
    SupplierIntervalLedger,
    _utc,
    gas_calorific_value_diagnostic,
)
from .providers.entity_map import KEMSEntities

_LOGGER = logging.getLogger(__name__)
_REFRESH = timedelta(minutes=30)
_BASELINE_REFRESH = timedelta(seconds=60)
_HISTORY_BATCH_DAYS = 7
_HISTORY_MAX_BATCHES = 12
_FILE_NAME = "kems_supplier_intervals.json"
_GAS_REFERENCE_FILE = "kems_gas_daily_reference.json"
_CHARGE_FILE = "kems_supplier_charges.json"
_MAX_FILE_BYTES = 10_000_000


def _read_bootstrap(path: Path) -> Any:
    if not path.is_file():
        return None
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("Supplier interval bootstrap exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


class SupplierIntervalRecorder:
    """Retain published supplier readings without blocking physical decisions."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._ledger = SupplierIntervalLedger()
        self._charges = SupplierChargeEvidence()
        self._late_events: dict[str, Any] = {}
        self._completed_ids: set[str] = set()
        self._store = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.supplier_intervals"
        )
        self._next_at: datetime | None = None
        self._dirty = False
        self._history_task = None
        self._history_anchor: datetime | None = None
        self._history_entities: dict[str, str] = {}
        self._history_batches = 0
        self._history_candidate_rows = 0
        self._history_changed = False
        self._next_baseline_at: datetime | None = None
        self._baseline_status: dict[str, Any] = {}
        self._history_status = {"status": "not_attempted"}
        self._status: dict[str, Any] = {"status": "not_loaded"}

    @property
    def status(self) -> dict[str, Any]:
        return {
            **self._status,
            "historical_charge_recovery": dict(self._history_status),
            "power_down_baseline_capture": dict(self._baseline_status),
        }

    def electricity_reconciliation(self, daily_records, *, now):
        return self._ledger.electricity_reconciliation(daily_records, now=now)

    def financial_reconciliation(self, daily_records, *, now, commissioning_date):
        return self._charges.reconciliation(
            self._ledger, daily_records, now=now, commissioning_date=commissioning_date
        )

    @property
    def late_power_down_evidence(self):
        return {
            "scope": "supplier_meter_and_exact_baseline_estimates",
            "events": [
                completed_power_down_estimate(self._ledger, item)
                for item in list(self._late_events.values())[-64:]
                if item.get("session_id") in self._completed_ids
            ],
            "joined_baselines_retained": [
                item
                for item in self._late_events.values()
                if item.get("session_id") not in self._completed_ids
            ],
            "supplier_settled": False,
            "roi_or_ledger_write_authorised": False,
        }

    def _dump(self):
        return {
            **self._ledger.dump(),
            "charge_evidence": self._charges.dump(),
            "late_power_down_evidence": self._late_events,
            "completed_power_down_ids": sorted(self._completed_ids),
        }

    async def _async_read_charge_file(self, now):
        try:
            data = await self._hass.async_add_executor_job(
                _read_bootstrap, Path(self._hass.config.path(_CHARGE_FILE))
            )
            if isinstance(data, dict) and data.get("format") == CHARGE_FORMAT:
                self._dirty |= await self._hass.async_add_executor_job(
                    lambda: self._charges.ingest(
                        data.get("rows") or [], source="octopus_csv", now=now
                    )
                )
        except (OSError, ValueError, TypeError):
            _LOGGER.warning("KEMS supplier charge reference file not accepted")

    async def async_load(self) -> None:
        now = datetime.now(UTC)
        try:
            stored = await self._store.async_load()
            await self._hass.async_add_executor_job(
                lambda: self._ledger.restore(stored, now=now)
            )
            if isinstance(stored, dict):
                await self._hass.async_add_executor_job(
                    lambda: self._charges.restore(
                        stored.get("charge_evidence"), now=now
                    )
                )
                events = stored.get("late_power_down_evidence")
                if isinstance(events, dict):
                    self._late_events = {
                        key: value
                        for key, value in events.items()
                        if isinstance(key, str) and isinstance(value, dict)
                    }
                completed_ids = stored.get("completed_power_down_ids")
                self._completed_ids = (
                    {
                        key
                        for key in completed_ids
                        if isinstance(key, str) and key in self._late_events
                    }
                    if isinstance(completed_ids, list)
                    else set(self._late_events)
                )
            await self._async_read_charge_file(now)
            path = Path(self._hass.config.path(_FILE_NAME))
            data = await self._hass.async_add_executor_job(_read_bootstrap, path)
            if isinstance(data, dict) and data.get("format") == FORMAT:
                changed = await self._hass.async_add_executor_job(
                    lambda: self._ledger.ingest(
                        data.get("rows") or [], source="octopus_csv", now=now
                    )
                )
                self._dirty |= changed
                self._dirty |= await self._hass.async_add_executor_job(
                    lambda: self._charges.ingest(
                        data.get("rows") or [], source="octopus_csv", now=now
                    )
                )
            # Persist the migration even if the original CSV is unchanged.
            self._dirty |= (
                bool(self._ledger.quarantined_gas)
                and isinstance(stored, dict)
                and "quarantined_gas_rows" not in stored
            )
            reference_path = Path(self._hass.config.path(_GAS_REFERENCE_FILE))
            try:
                reference = await self._hass.async_add_executor_job(
                    _read_bootstrap, reference_path
                )
                if (
                    isinstance(reference, dict)
                    and reference.get("format") == "kems-gas-daily-reference-v1"
                ):
                    self._dirty |= await self._hass.async_add_executor_job(
                        lambda: self._ledger.ingest_gas_daily_reference(
                            reference.get("rows") or [], now=now
                        )
                    )
            except (OSError, ValueError, TypeError):
                _LOGGER.warning("KEMS gas daily reference file not accepted")
            if self._dirty:
                await self._store.async_save(self._dump())
                self._dirty = False
            self._status = await self._hass.async_add_executor_job(self._ledger.summary)
        except Exception:
            _LOGGER.exception("KEMS supplier interval recovery unavailable")
            self._status = {"status": "load_failed"}

    def _retain_baseline(self, evidence):
        key = evidence["session_id"]
        prior = self._late_events.get(key)
        merged = merge_completed_baseline(prior, evidence) if prior else evidence
        if merged == prior:
            return False
        self._late_events[key] = merged
        return True

    async def _recover_recorded_charges(self, entities, start, end):
        """One bounded, read-only query outside the live coordinator scan."""
        from homeassistant.components.recorder import get_instance, history

        def read():
            states = history.get_significant_states(
                self._hass,
                start,
                end,
                entity_ids=list(entities),
                include_start_time_state=False,
                significant_changes_only=False,
                minimal_response=False,
                no_attributes=False,
            )
            # Repeated HA states can contain identical charge attributes.
            # Collapse only byte-equivalent observations; retain revisions.
            result = {}
            for entity_id, kind in entities.items():
                for state in states.get(entity_id, []):
                    if state.state in {"unknown", "unavailable"}:
                        continue
                    for row in supplier_cost_rows(kind, state.attributes):
                        key = tuple(str(value) for value in row.values())
                        result[key] = row
            return list(result.values())

        return await get_instance(self._hass).async_add_executor_job(read)

    async def _consume_recorded_charges(self, now, entities):
        """Read at most one seven-day batch per normal supplier scan."""
        changed = False
        if self._history_task is not None:
            if not self._history_task.done():
                return False
            task, self._history_task = self._history_task, None
            try:
                rows = task.result()
                changed = await self._hass.async_add_executor_job(
                    lambda: self._charges.ingest(
                        rows, source="octopus_integration", now=now
                    )
                )
                self._history_candidate_rows += len(rows)
                self._history_changed |= changed
                self._history_batches += 1
                self._history_status = {
                    "status": (
                        "observed"
                        if self._history_candidate_rows
                        else "no_retained_attributes"
                    ),
                    "candidate_rows": self._history_candidate_rows,
                    "last_batch_candidate_rows": len(rows),
                    "evidence_changed": self._history_changed,
                    "lookback_days": self._history_batches * _HISTORY_BATCH_DAYS,
                    "completed_batches": self._history_batches,
                    "max_batches": _HISTORY_MAX_BATCHES,
                    "supplier_settlement_verified": False,
                }
                # An empty historical window is not proof older data exist.
                # Stop here to avoid repeated queries against purged history.
                if not rows:
                    self._history_status["stop_reason"] = "empty_window"
                    return changed
            except Exception as err:
                self._history_status = {
                    **self._history_status,
                    "status": "unavailable",
                    "error_type": type(err).__name__,
                    "stop_reason": "query_failed",
                }
                return False
        if not entities:
            return changed
        # Resolve a new meter mapping with a fresh cursor. Existing evidence
        # is retained and duplicate charge rows are idempotent.
        if dict(entities) != self._history_entities:
            self._history_entities = dict(entities)
            self._history_anchor = now
            self._history_batches = 0
            self._history_candidate_rows = 0
            self._history_changed = False
            self._history_status = {"status": "not_attempted"}
        if (
            self._history_batches >= _HISTORY_MAX_BATCHES
            or self._history_status.get("stop_reason")
        ):
            return changed
        if self._history_anchor is None:
            self._history_anchor = now
        end = self._history_anchor - timedelta(
            days=self._history_batches * _HISTORY_BATCH_DAYS
        )
        start = end - timedelta(days=_HISTORY_BATCH_DAYS)
        self._history_status.update(
            {
                "status": "querying",
                "query_start": start.isoformat(),
                "query_end": end.isoformat(),
                "max_batches": _HISTORY_MAX_BATCHES,
                "supplier_settlement_verified": False,
            }
        )
        self._history_task = self._hass.async_create_background_task(
            self._recover_recorded_charges(dict(entities), start, end),
            "KEMS read-only supplier charge history recovery",
        )
        return changed

    def _observe_baselines(self, now, entities, completed_events):
        changed = False
        observations = []
        import_state = self._hass.states.get(
            entities.saving_session_import_baseline or ""
        )
        export_state = self._hass.states.get(
            entities.saving_session_export_baseline or ""
        )
        event_state = self._hass.states.get(entities.saving_session_events or "")
        if completed_events or event_state is not None:
            import_attrs = (
                import_state.attributes
                if import_state is not None
                and import_state.state not in {"unknown", "unavailable"}
                else {}
            )
            export_attrs = (
                export_state.attributes
                if export_state is not None
                and export_state.state not in {"unknown", "unavailable"}
                else {}
            )
            joined = (
                event_state.attributes.get("joined_events", [])
                if event_state is not None
                and event_state.state not in {"unknown", "unavailable"}
                else []
            )
            if not isinstance(joined, list):
                joined = []
            for item in joined:
                if not isinstance(item, dict):
                    continue
                evidence = capture_joined_baseline(
                    item,
                    import_attrs,
                    export_attrs,
                    now=now,
                    retain_event_identity=True,
                )
                if evidence is not None:
                    changed |= self._retain_baseline(evidence)
                    start = _utc(evidence["session_start"])
                    end = _utc(evidence["session_end"])
                    observations.append(
                        {
                            "session_id": evidence["session_id"],
                            "import": baseline_capture_diagnostic(
                                import_attrs, start, end
                            ),
                            "export": baseline_capture_diagnostic(
                                export_attrs, start, end
                            ),
                        }
                    )
            for result in completed_events:
                event = result.to_dict()
                # Only the exact retained joined event may provide a rate.
                points = None
                for item in joined:
                    if (
                        isinstance(item, dict)
                        and str(item.get("id")) == str(event.get("session_id"))
                        and _utc(item.get("start"))
                        == _utc(event.get("session_start"))
                        and _utc(item.get("end")) == _utc(event.get("session_end"))
                    ):
                        points = item.get("octopoints_per_kwh")
                        break
                evidence = capture_completed_baseline(
                    event,
                    import_attrs,
                    export_attrs,
                    now=now,
                    points_per_kwh=points,
                    allow_partial=True,
                )
                if evidence is None:
                    continue
                key = evidence["session_id"]
                if key not in self._completed_ids:
                    self._completed_ids.add(key)
                    changed = True
                changed |= self._retain_baseline(evidence)
            if len(self._late_events) > 64:
                self._late_events = dict(
                    sorted(
                        self._late_events.items(),
                        key=lambda pair: str(pair[1].get("session_end") or ""),
                    )[-64:]
                )
                self._completed_ids.intersection_update(self._late_events)
                changed = True
        last_nonempty = self._baseline_status.get(
            "last_nonempty_source_observations", []
        )
        if any(
            item[direction]["rows_reported"]
            for item in observations
            for direction in ("import", "export")
        ):
            last_nonempty = observations[-8:]
        self._baseline_status = {
            "last_nonempty_source_observations": last_nonempty,
            "last_scan_at": now.isoformat(),
            "scan_interval_seconds": int(_BASELINE_REFRESH.total_seconds()),
            "joined_event_observations": observations[-8:],
            "supplier_settlement_verified": False,
        }
        return changed

    async def async_observe(
        self, now: datetime, entities: KEMSEntities, completed_events=()
    ) -> None:
        if self._status.get("status") == "load_failed":
            return
        # Baseline attributes may disappear immediately after an event.
        # Observe them independently of the slower historical intake.
        if self._next_baseline_at is None or now >= self._next_baseline_at:
            self._next_baseline_at = now + _BASELINE_REFRESH
            try:
                self._dirty |= self._observe_baselines(
                    now, entities, completed_events
                )
                if self._dirty:
                    await self._store.async_save(self._dump())
                    self._dirty = False
            except Exception:
                _LOGGER.exception("KEMS Power Down baseline observation failed")
                self._baseline_status["observation_failed"] = True
        if self._next_at is not None and now < self._next_at:
            return
        self._next_at = now + _REFRESH
        try:
            registry = er.async_get(self._hass)
            mapping = {
                "electricity_import": entities.current_import_rate,
                "electricity_export": entities.current_export_rate,
                "gas": entities.gas_current_rate,
            }
            found = {kind: [] for kind in KINDS}
            cost_index = {}
            for item in registry.entities.values():
                if item.platform != "octopus_energy" or item.disabled_by is not None:
                    continue
                uid = item.unique_id.casefold()
                if uid.endswith("_previous_accumulative_cost"):
                    cost_index.setdefault((item.config_entry_id, uid), []).append(item)
                if uid.startswith("octopus_energy_electricity_") and uid.endswith(
                    "_previous_accumulative_consumption"
                ):
                    kind = (
                        "electricity_export"
                        if uid.endswith("_export_previous_accumulative_consumption")
                        else "electricity_import"
                    )
                elif uid.startswith("octopus_energy_gas_") and uid.endswith(
                    "_previous_accumulative_consumption_kwh"
                ):
                    kind = "gas"
                else:
                    continue
                # Require the same account AND meter prefix as the configured
                # tariff sensor, not just a plausible name in another account.
                mapped = registry.async_get(mapping[kind] or "")
                if (
                    mapped is None
                    or mapped.platform != "octopus_energy"
                    or mapped.config_entry_id != item.config_entry_id
                    or not mapped.unique_id.casefold().endswith("_current_rate")
                ):
                    continue
                expected_uid = (
                    mapped.unique_id.casefold().removesuffix("_current_rate")
                    + "_previous_accumulative_consumption"
                )
                if kind == "gas":
                    expected_uid += "_kwh"
                if uid != expected_uid:
                    continue
                found[kind].append(item.entity_id)
            changed = False
            availability = {}
            charge_availability = {}
            gas_source_shape = None
            history_entities = {}
            await self._async_read_charge_file(now)
            for kind, candidates in found.items():
                availability[kind] = "ambiguous_or_unmapped"
                if len(candidates) != 1:
                    continue
                if kind != "gas":
                    meter = registry.async_get(mapping[kind] or "")
                    expected = (
                        meter.unique_id.casefold().removesuffix("_current_rate")
                        + "_previous_accumulative_cost"
                    )
                    cost_matches = cost_index.get((meter.config_entry_id, expected), [])
                    charge_availability[kind] = "unavailable_or_ambiguous"
                    if len(cost_matches) == 1:
                        history_entities[cost_matches[0].entity_id] = kind
                state = self._hass.states.get(candidates[0])
                if (
                    state is None
                    or state.state in {"unknown", "unavailable"}
                    or state.attributes.get("unit_of_measurement") != "kWh"
                ):
                    availability[kind] = "unavailable"
                    continue
                attrs = state.attributes
                if kind != "gas" and attrs.get("is_export") is not (
                    kind == "electricity_export"
                ):
                    continue
                charges = attrs.get("charges")
                if not isinstance(charges, list):
                    continue
                key = "consumption_kwh" if kind == "gas" else "consumption"
                rows = [
                    {
                        "kind": kind,
                        "start": row.get("start"),
                        "end": row.get("end"),
                        "kwh": row.get(key),
                        "consumption_m3": row.get("consumption_m3"),
                    }
                    for row in charges
                    if isinstance(row, dict)
                ]
                source = (
                    "octopus_estimated_gas"
                    if kind == "gas" and attrs.get("is_estimated") is not False
                    else "octopus_integration"
                )
                changed |= self._ledger.ingest(rows, source=source, now=now)
                availability[kind] = (
                    "quarantined_unverified" if kind == "gas" else "observed"
                )
                if kind == "gas":
                    gas_source_shape = {
                        "reported_unit": state.attributes.get("unit_of_measurement"),
                        "estimated": attrs.get("is_estimated"),
                        "charge_rows": len(charges),
                        "row_fields": sorted(
                            {
                                str(field)
                                for row in charges
                                if isinstance(row, dict)
                                for field in row
                            }
                        ),
                        "used_consumption_field": key,
                        "financially_usable": False,
                        "conversion_setting": gas_calorific_value_diagnostic(attrs),
                    }
                    continue
                if len(cost_matches) != 1:
                    continue
                cost_state = self._hass.states.get(cost_matches[0].entity_id)
                if (
                    cost_state is None
                    or cost_state.state in {"unknown", "unavailable"}
                    or cost_state.attributes.get("unit_of_measurement") != "GBP"
                    or cost_state.attributes.get("is_export")
                    is not (kind == "electricity_export")
                ):
                    continue
                priced = supplier_cost_rows(kind, cost_state.attributes)
                changed |= self._charges.ingest(
                    priced, source="octopus_integration", now=now
                )
                charge_availability[kind] = "estimated_charges_observed"

            changed |= await self._consume_recorded_charges(now, history_entities)

            self._dirty |= changed
            if self._dirty:
                await self._store.async_save(self._dump())
                self._dirty = False
                self._status = await self._hass.async_add_executor_job(
                    self._ledger.summary
                )
            self._status["automatic_source_status"] = availability
            self._status["automatic_charge_source_status"] = charge_availability
            self._status["gas_source_shape"] = gas_source_shape
            self._status["last_scan_at"] = now.isoformat()
            self._status.pop("automatic_observation_failed", None)
        except Exception:
            _LOGGER.exception("KEMS supplier interval observation failed")
            self._status["automatic_observation_failed"] = True
