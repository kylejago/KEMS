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
    capture_completed_baseline,
    completed_power_down_estimate,
)
from .kems_core.supplier_intervals import FORMAT, KINDS, SupplierIntervalLedger, _utc
from .providers.entity_map import KEMSEntities

_LOGGER = logging.getLogger(__name__)
_REFRESH = timedelta(minutes=30)
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
        self._store = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.supplier_intervals"
        )
        self._next_at: datetime | None = None
        self._dirty = False
        self._status: dict[str, Any] = {"status": "not_loaded"}

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)

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
            ],
            "supplier_settled": False,
            "roi_or_ledger_write_authorised": False,
        }

    def _dump(self):
        return {
            **self._ledger.dump(),
            "charge_evidence": self._charges.dump(),
            "late_power_down_evidence": self._late_events,
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

    async def async_observe(
        self, now: datetime, entities: KEMSEntities, completed_events=()
    ) -> None:
        if self._status.get("status") == "load_failed":
            return
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
            for item in registry.entities.values():
                if item.platform != "octopus_energy" or item.disabled_by is not None:
                    continue
                uid = item.unique_id.casefold()
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
            await self._async_read_charge_file(now)
            for kind, candidates in found.items():
                availability[kind] = "ambiguous_or_unmapped"
                if len(candidates) != 1:
                    continue
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
                    continue
                meter = registry.async_get(mapping[kind] or "")
                expected = (
                    meter.unique_id.casefold().removesuffix("_current_rate")
                    + "_previous_accumulative_cost"
                )
                cost_matches = [
                    item
                    for item in registry.entities.values()
                    if item.platform == "octopus_energy"
                    and item.disabled_by is None
                    and item.config_entry_id == meter.config_entry_id
                    and item.unique_id.casefold() == expected
                ]
                charge_availability[kind] = "unavailable_or_ambiguous"
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
                cost_rows = cost_state.attributes.get("charges")
                if not isinstance(cost_rows, list):
                    continue
                priced = []
                for row in cost_rows:
                    if not isinstance(row, dict):
                        continue
                    try:
                        cost = float(row.get("raw_cost")) * 100
                    except (TypeError, ValueError, OverflowError):
                        continue
                    priced.append(
                        {
                            "kind": kind,
                            "start": row.get("start"),
                            "end": row.get("end"),
                            "kwh": row.get("consumption"),
                            "charge_pence": cost,
                        }
                    )
                changed |= self._charges.ingest(
                    priced, source="octopus_integration", now=now
                )
                charge_availability[kind] = "estimated_charges_observed"

            import_state = self._hass.states.get(
                entities.saving_session_import_baseline or ""
            )
            export_state = self._hass.states.get(
                entities.saving_session_export_baseline or ""
            )
            event_state = self._hass.states.get(entities.saving_session_events or "")
            if (
                import_state is not None
                and export_state is not None
                and import_state.state not in {"unknown", "unavailable"}
                and export_state.state not in {"unknown", "unavailable"}
            ):
                joined = (
                    event_state.attributes.get("joined_events", [])
                    if event_state
                    else []
                )
                if not isinstance(joined, list):
                    joined = []
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
                        import_state.attributes,
                        export_state.attributes,
                        now=now,
                        points_per_kwh=points,
                    )
                    if evidence is None:
                        continue
                    key = evidence["session_id"]
                    prior = self._late_events.get(key)
                    if prior is None:
                        self._late_events[key] = evidence
                        changed = True
                    elif not prior.get("conflict"):
                        comparable = (
                            "session_start",
                            "session_end",
                            "import_baseline_kwh",
                            "export_baseline_kwh",
                        )
                        if any(prior.get(k) != evidence.get(k) for k in comparable) or (
                            prior.get("octopoints_per_kwh") is not None
                            and evidence.get("octopoints_per_kwh") is not None
                            and prior["octopoints_per_kwh"]
                            != evidence["octopoints_per_kwh"]
                        ):
                            self._late_events[key] = {**prior, "conflict": True}
                            changed = True
                        elif (
                            prior.get("octopoints_per_kwh") is None
                            and evidence.get("octopoints_per_kwh") is not None
                        ):
                            self._late_events[key] = evidence
                            changed = True
                if len(self._late_events) > 64:
                    self._late_events = dict(list(self._late_events.items())[-64:])
                    changed = True
            self._dirty |= changed
            if self._dirty:
                await self._store.async_save(self._dump())
                self._dirty = False
                self._status = await self._hass.async_add_executor_job(
                    self._ledger.summary
                )
            self._status["automatic_source_status"] = availability
            self._status["automatic_charge_source_status"] = charge_availability
            self._status["last_scan_at"] = now.isoformat()
            self._status.pop("automatic_observation_failed", None)
        except Exception:
            _LOGGER.exception("KEMS supplier interval observation failed")
            self._status["automatic_observation_failed"] = True
