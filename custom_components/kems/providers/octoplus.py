"""Octoplus Power Down / Saving Session state provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities

BaselineTuple = tuple[
    float | None,
    float | None,
    datetime | None,
    datetime | None,
    bool | None,
]


@dataclass(frozen=True, slots=True)
class OctoplusState:
    """Current or next joined Octoplus Power Down / Saving Session."""

    joined: bool = False
    active: bool = False
    event_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    octopoints_per_kwh: float | None = None
    import_baseline_period_kwh: float | None = None
    export_baseline_period_kwh: float | None = None
    import_baseline_total_kwh: float | None = None
    export_baseline_total_kwh: float | None = None
    baseline_period_start: datetime | None = None
    baseline_period_end: datetime | None = None
    baseline_incomplete: bool | None = None


class OctoplusProvider(HomeAssistantStateReader):
    """Read joined Power Down sessions and optional baseline entities."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        super().__init__(hass)
        self._entities = entities

    def get_state(self, now: datetime | None = None) -> OctoplusState:
        """Return the active event, otherwise the next joined event."""
        reference = now or dt_util.now()
        event_state = self._state(self._entities.saving_session_events)
        event = self._select_joined_event(event_state, reference)
        import_baseline = self._baseline(
            self._state(self._entities.saving_session_import_baseline)
        )
        export_baseline = self._baseline(
            self._state(self._entities.saving_session_export_baseline)
        )
        import_baseline, export_baseline = self._reward_baselines(
            import_baseline,
            export_baseline,
            export_configured=bool(self._entities.saving_session_export_baseline),
        )
        if event is None:
            return OctoplusState(
                import_baseline_period_kwh=import_baseline[0],
                export_baseline_period_kwh=export_baseline[0],
                import_baseline_total_kwh=import_baseline[1],
                export_baseline_total_kwh=export_baseline[1],
                baseline_period_start=import_baseline[2] or export_baseline[2],
                baseline_period_end=import_baseline[3] or export_baseline[3],
                baseline_incomplete=self._combine_incomplete(
                    import_baseline[4], export_baseline[4]
                ),
            )
        start = self._parse_datetime(event.get("start"))
        end = self._parse_datetime(event.get("end"))
        active = bool(start and end and start <= reference < end)
        points = self._number(event.get("octopoints_per_kwh"))
        event_id = event.get("id")
        return OctoplusState(
            joined=True,
            active=active,
            event_id=str(event_id) if event_id is not None else None,
            start=start,
            end=end,
            octopoints_per_kwh=points,
            import_baseline_period_kwh=import_baseline[0],
            export_baseline_period_kwh=export_baseline[0],
            import_baseline_total_kwh=import_baseline[1],
            export_baseline_total_kwh=export_baseline[1],
            baseline_period_start=import_baseline[2] or export_baseline[2],
            baseline_period_end=import_baseline[3] or export_baseline[3],
            baseline_incomplete=self._combine_incomplete(
                import_baseline[4], export_baseline[4]
            ),
        )

    @staticmethod
    def _reward_baselines(
        import_baseline: BaselineTuple,
        export_baseline: BaselineTuple,
        *,
        export_configured: bool,
    ) -> tuple[BaselineTuple, BaselineTuple]:
        """Fail closed when an applicable export baseline is not usable yet.

        Octopus calculates Power Down rewards from the site's net change when an
        export MPAN participates. KEMS therefore must not silently substitute zero
        historical export when an export-baseline source has been discovered but is
        disabled, unavailable, or not populated yet. Physical Power Down planning is
        independent of these values and continues normally; only reward accounting is
        withheld until the matching export baseline becomes usable.
        """
        if not export_configured:
            return import_baseline, export_baseline

        import_period, import_total, import_start, import_end, import_incomplete = (
            import_baseline
        )
        export_period, export_total, export_start, export_end, export_incomplete = (
            export_baseline
        )
        if export_period is None:
            import_period = None
        if export_total is None:
            import_total = None
        return (
            (
                import_period,
                import_total,
                import_start,
                import_end,
                import_incomplete,
            ),
            (
                export_period,
                export_total,
                export_start,
                export_end,
                export_incomplete,
            ),
        )

    @classmethod
    def _select_joined_event(
        cls,
        state: State | None,
        now: datetime,
    ) -> dict[str, Any] | None:
        if state is None:
            return None
        joined = state.attributes.get("joined_events")
        if not isinstance(joined, list):
            return None
        valid: list[tuple[datetime, datetime, dict[str, Any]]] = []
        for item in joined:
            if not isinstance(item, dict):
                continue
            start = cls._parse_datetime(item.get("start"))
            end = cls._parse_datetime(item.get("end"))
            if start is None or end is None or end <= now:
                continue
            valid.append((start, end, item))
        if not valid:
            return None
        active = [item for item in valid if item[0] <= now < item[1]]
        selected = min(active or valid, key=lambda item: item[0])
        return selected[2]

    @classmethod
    def _baseline(
        cls,
        state: State | None,
    ) -> BaselineTuple:
        if state is None:
            return None, None, None, None, None
        period = cls._number(state.state)
        total = cls._number(state.attributes.get("total_baseline"))
        if total is None:
            baselines = state.attributes.get("baselines")
            if isinstance(baselines, list):
                values = [
                    cls._number(item.get("baseline"))
                    for item in baselines
                    if isinstance(item, dict)
                ]
                known = [value for value in values if value is not None]
                total = sum(known) if known else None
        return (
            period,
            total,
            cls._parse_datetime(state.attributes.get("start")),
            cls._parse_datetime(state.attributes.get("end")),
            cls._bool_value(state.attributes.get("is_incomplete_calculation")),
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bool_value(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _combine_incomplete(first: bool | None, second: bool | None) -> bool | None:
        values = [value for value in (first, second) if value is not None]
        return any(values) if values else None
