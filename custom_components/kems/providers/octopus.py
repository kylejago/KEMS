"""Octopus Energy electricity state provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities

DEFAULT_INTELLIGENT_STALE_DATA_SECONDS = 360
INTELLIGENT_SOURCE_FIELDS = frozenset(
    {"intelligent_slot", "next_offpeak_start", "offpeak_end"}
)
OPTIONAL_TIMESTAMP_FIELDS = frozenset({"next_offpeak_start", "offpeak_end"})


@dataclass(frozen=True, slots=True)
class OctopusState:
    """Current Octopus electricity tariff observation."""

    current_import_rate: float | None = None
    next_import_rate: float | None = None
    current_export_rate: float | None = None
    electricity_standing_charge: float | None = None
    off_peak: bool | None = None
    intelligent_slot: bool | None = None
    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None
    source_age_seconds: dict[str, float] = field(default_factory=dict)
    stale_fields: tuple[str, ...] = ()
    source_data_age_seconds: float | None = None


class OctopusProvider(HomeAssistantStateReader):
    """Read data from configured Octopus Energy electricity entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entities: KEMSEntities,
        stale_data_seconds: int = 180,
        intelligent_stale_data_seconds: int = DEFAULT_INTELLIGENT_STALE_DATA_SECONDS,
    ) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities
        self._stale_data_seconds = max(int(stale_data_seconds), 30)
        self._intelligent_stale_data_seconds = max(
            int(intelligent_stale_data_seconds),
            self._stale_data_seconds,
            30,
        )

    def get_state(self, now: datetime | None = None) -> OctopusState:
        """Return tariff data while rejecting individually stale sources."""
        reference = now or dt_util.now()
        ages: dict[str, float] = {}
        stale: set[str] = set()

        def age_for(logical_name: str, entity_id: str | None) -> float | None:
            # Intelligent schedule integrations legitimately publish unknown for
            # next-start/end timestamps when that boundary is not currently
            # applicable. Absence is not the same thing as a stale positive
            # signal, so do not turn an old `unknown` timestamp into a warning.
            if (
                logical_name in OPTIONAL_TIMESTAMP_FIELDS
                and self._datetime(entity_id) is None
            ):
                return None
            age = self._report_age_seconds(entity_id, reference)
            if age is not None:
                ages[logical_name] = round(age, 1)
            return age

        def source_is_usable(logical_name: str, entity_id: str | None) -> bool:
            age = age_for(logical_name, entity_id)
            timeout = (
                self._intelligent_stale_data_seconds
                if logical_name in INTELLIGENT_SOURCE_FIELDS
                else self._stale_data_seconds
            )
            if age is not None and age > timeout:
                stale.add(logical_name)
                return False
            return True

        def fresh_rate(logical_name: str, entity_id: str | None) -> float | None:
            if not source_is_usable(logical_name, entity_id):
                return None
            return self._rate_pence(entity_id)

        def fresh_money(logical_name: str, entity_id: str | None) -> float | None:
            if not source_is_usable(logical_name, entity_id):
                return None
            return self._money_pence(entity_id)

        def fresh_bool(logical_name: str, entity_id: str | None) -> bool | None:
            if not source_is_usable(logical_name, entity_id):
                return None
            return self._bool(entity_id)

        def fresh_datetime(
            logical_name: str,
            entity_id: str | None,
        ) -> datetime | None:
            if not source_is_usable(logical_name, entity_id):
                return None
            return self._datetime(entity_id)

        intelligent_slot = fresh_bool(
            "intelligent_slot",
            self._entities.intelligent_slot,
        )
        if "intelligent_slot" in stale:
            # Fail closed: a stale positive extra-slot state must become False,
            # never a still-authoritative cheap-period signal.
            intelligent_slot = False

        state = OctopusState(
            current_import_rate=fresh_rate(
                "current_import_rate",
                self._entities.current_import_rate,
            ),
            next_import_rate=fresh_rate(
                "next_import_rate",
                self._entities.next_import_rate,
            ),
            current_export_rate=fresh_rate(
                "current_export_rate",
                self._entities.current_export_rate,
            ),
            electricity_standing_charge=fresh_money(
                "electricity_standing_charge",
                self._entities.electricity_standing_charge,
            ),
            off_peak=fresh_bool("off_peak", self._entities.off_peak),
            intelligent_slot=intelligent_slot,
            next_offpeak_start=fresh_datetime(
                "next_offpeak_start",
                self._entities.next_offpeak_start,
            ),
            offpeak_end=fresh_datetime(
                "offpeak_end",
                self._entities.offpeak_end,
            ),
            source_age_seconds=ages,
            stale_fields=tuple(sorted(stale)),
            source_data_age_seconds=max(ages.values()) if ages else None,
        )
        return state
