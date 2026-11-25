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
from .kems_core.supplier_intervals import FORMAT, KINDS, SupplierIntervalLedger
from .providers.entity_map import KEMSEntities

_LOGGER = logging.getLogger(__name__)
_REFRESH = timedelta(minutes=30)
_FILE_NAME = "kems_supplier_intervals.json"
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
        self._store = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.supplier_intervals"
        )
        self._next_at: datetime | None = None
        self._dirty = False
        self._status: dict[str, Any] = {"status": "not_loaded"}

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def async_load(self) -> None:
        now = datetime.now(UTC)
        try:
            stored = await self._store.async_load()
            await self._hass.async_add_executor_job(
                lambda: self._ledger.restore(stored, now=now)
            )
            path = Path(self._hass.config.path(_FILE_NAME))
            data = await self._hass.async_add_executor_job(_read_bootstrap, path)
            if isinstance(data, dict) and data.get("format") == FORMAT:
                changed = await self._hass.async_add_executor_job(
                    lambda: self._ledger.ingest(
                        data.get("rows") or [], source="octopus_csv", now=now
                    )
                )
                if changed:
                    await self._store.async_save(self._ledger.dump())
            self._status = await self._hass.async_add_executor_job(self._ledger.summary)
        except Exception:
            _LOGGER.exception("KEMS supplier interval recovery unavailable")
            self._status = {"status": "load_failed"}

    async def async_observe(self, now: datetime, entities: KEMSEntities) -> None:
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
                availability[kind] = "observed"
            self._dirty |= changed
            if self._dirty:
                await self._store.async_save(self._ledger.dump())
                self._dirty = False
                self._status = await self._hass.async_add_executor_job(
                    self._ledger.summary
                )
            self._status["automatic_source_status"] = availability
            self._status["last_scan_at"] = now.isoformat()
            self._status.pop("automatic_observation_failed", None)
        except Exception:
            _LOGGER.exception("KEMS supplier interval observation failed")
            self._status["automatic_observation_failed"] = True
