"""Keep the settled Agile SOC authoritative across the local-day rollover.

The normal day replay is useful for accounting, but its ending SOC can differ
from the current-day settled digital twin after deliberate export has been
reconciled.  During the active 23:30 cheap window KEMS already knows the
settled/current SOC and can project the remaining cheap charge to 00:00.  This
module persists that handoff and makes it the next day's Agile replay seed.

Recorder samples are also not guaranteed to land on exactly 00:00:00.  When a
small real observation gap straddles local midnight, a timestamp-only boundary
copy closes the final pre-midnight integration interval.  No power, SOC, or
other telemetry value is invented.

This is simulation/reporting continuity only.  It does not alter live Agile
routing, Power Down ownership, cheap-charge control, or hardware permissions.
Real hardware writes remain blocked.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import agile_smart_export as agile
from .agile_current_day_settlement import SettledCurrentDayAgileSmartExportManager
from .const import DOMAIN

ROLLOVER_STORE_VERSION = 1
MAX_SYNTHETIC_MIDNIGHT_GAP = timedelta(minutes=10)
ACTIVE_CHEAP_HANDOFF_BASIS = "current SOC inside active cheap window"
SETTLED_ROLLOVER_SOURCE = "settled/current SOC projected through active cheap window"


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _date_text(value: Any) -> str | None:
    """Return one ISO local date string when valid."""
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except (TypeError, ValueError):
        return None


def _seed_is_valid(seed: Any) -> bool:
    """Return whether a persisted rollover seed is complete and finite."""
    if not isinstance(seed, dict):
        return False
    if _number(seed.get("agile_midnight_soc_percent")) is None:
        return False
    try:
        source = datetime.fromisoformat(str(seed["source_date"]) + "T00:00:00")
        target = datetime.fromisoformat(str(seed["target_date"]) + "T00:00:00")
    except (KeyError, TypeError, ValueError):
        return False
    return target.date() == source.date() + timedelta(days=1)


class MidnightRolloverAgileSmartExportManager(
    SettledCurrentDayAgileSmartExportManager
):
    """Preserve settled pre-midnight SOC as the following day's Agile seed."""

    def __init__(self, hass: HomeAssistant, entry_id: str, history_days: int) -> None:
        super().__init__(hass, entry_id, history_days)
        self._midnight_rollover_store: Store[dict[str, Any]] = Store(
            hass,
            ROLLOVER_STORE_VERSION,
            f"{DOMAIN}.{entry_id}.agile_midnight_rollover",
        )
        self._settled_midnight_rollover_seed: dict[str, Any] | None = None
        self._midnight_rollover_seed_dirty = False
        self._midnight_rollover_now_date = None
        self._settled_midnight_seed_applied = False
        self._settled_midnight_stale_replay_soc: float | None = None
        self._synthetic_midnight_boundary_days: set[str] = set()

    async def async_load(self) -> None:
        """Restore the most recent settled rollover seed after HA restarts."""
        await super().async_load()
        data = await self._midnight_rollover_store.async_load() or {}
        seed = data.get("seed") if isinstance(data, dict) else None
        if _seed_is_valid(seed):
            self._settled_midnight_rollover_seed = dict(seed)

    async def _save_midnight_rollover_seed(self) -> None:
        """Persist the latest active-cheap-window handoff."""
        if not self._midnight_rollover_seed_dirty:
            return
        seed = self._settled_midnight_rollover_seed
        await self._midnight_rollover_store.async_save(
            {"seed": dict(seed) if isinstance(seed, dict) else None}
        )
        self._midnight_rollover_seed_dirty = False

    def _prepare_replay_continuity(self, records) -> None:
        """Add a truthful timestamp boundary when samples straddle midnight."""
        super()._prepare_replay_continuity(records)
        ordered = sorted(records, key=lambda item: item.timestamp)
        boundaries = getattr(self, "_midnight_replay_boundaries", {})
        self._synthetic_midnight_boundary_days = set()
        for previous, following in zip(ordered, ordered[1:], strict=False):
            previous_local = previous.timestamp.astimezone(agile.LONDON)
            following_local = following.timestamp.astimezone(agile.LONDON)
            if following_local.date() != previous_local.date() + timedelta(days=1):
                continue
            if following.timestamp - previous.timestamp > MAX_SYNTHETIC_MIDNIGHT_GAP:
                continue
            source_day = previous_local.date()
            if source_day in boundaries:
                continue
            midnight = datetime.combine(
                following_local.date(),
                time.min,
                tzinfo=agile.LONDON,
            )
            if not (previous_local < midnight < following_local):
                continue
            boundaries[source_day] = replace(following, timestamp=midnight)
            self._synthetic_midnight_boundary_days.add(source_day.isoformat())
        self._midnight_replay_boundaries = boundaries

    def _compare_day(
        self,
        records,
        config,
        tariff,
        agile_soc,
        full_soc,
        learned_forecast,
        projection: bool = False,
    ):
        """Let accounting replay run, then keep its stale SOC out of rollover."""
        result = super()._compare_day(
            records,
            config,
            tariff,
            agile_soc,
            full_soc,
            learned_forecast,
            projection=projection,
        )
        if projection or not records:
            return result

        seed = self._settled_midnight_rollover_seed
        if not _seed_is_valid(seed):
            return result
        source_day = records[0].timestamp.astimezone(agile.LONDON).date()
        current_day = self._midnight_rollover_now_date
        if current_day is None:
            return result
        if str(seed.get("source_date")) != source_day.isoformat():
            return result
        if str(seed.get("target_date")) != current_day.isoformat():
            return result

        seed_soc = _number(seed.get("agile_midnight_soc_percent"))
        agile_summary = result.get("agile_smart_export")
        if seed_soc is None or not isinstance(agile_summary, dict):
            return result
        replay_soc = _number(agile_summary.get("ending_soc_percent"))
        agile_summary["pre_rollover_replay_ending_soc_percent"] = replay_soc
        agile_summary["ending_soc_percent"] = round(seed_soc, 3)
        agile_summary["soc_rollover_source"] = SETTLED_ROLLOVER_SOURCE
        self._settled_midnight_seed_applied = True
        self._settled_midnight_stale_replay_soc = replay_soc
        return result

    def _capture_active_cheap_rollover_seed(self, now: datetime) -> None:
        """Capture only a handoff grounded in current SOC inside cheap time."""
        state = getattr(self, "_state", None)
        if not isinstance(state, dict):
            return
        handoff_root = state.get("tomorrow_soc_handoff")
        handoff_root = handoff_root if isinstance(handoff_root, dict) else {}
        handoff = handoff_root.get("agile")
        handoff = handoff if isinstance(handoff, dict) else {}
        if handoff.get("basis") != ACTIVE_CHEAP_HANDOFF_BASIS:
            return
        midnight_soc = _number(handoff.get("midnight_soc_percent"))
        handoff_end = handoff.get("handoff_end")
        try:
            target = datetime.fromisoformat(str(handoff_end))
        except (TypeError, ValueError):
            return
        if target.tzinfo is None or midnight_soc is None:
            return
        local_now = now.astimezone(agile.LONDON)
        target_local = target.astimezone(agile.LONDON)
        if target_local.date() != local_now.date() + timedelta(days=1):
            return

        reconciliation = state.get("settled_soc_handoff_reconciliation")
        reconciliation = (
            reconciliation if isinstance(reconciliation, dict) else {}
        )
        settled_soc = _number(reconciliation.get("settled_current_soc_percent"))
        seed = {
            "source_date": local_now.date().isoformat(),
            "target_date": target_local.date().isoformat(),
            "generated_at": now.isoformat(),
            "basis": ACTIVE_CHEAP_HANDOFF_BASIS,
            "source": SETTLED_ROLLOVER_SOURCE,
            "settled_current_soc_percent": settled_soc,
            "agile_midnight_soc_percent": round(midnight_soc, 3),
            "hardware_writes": "blocked",
        }
        if seed != self._settled_midnight_rollover_seed:
            self._settled_midnight_rollover_seed = seed
            self._midnight_rollover_seed_dirty = True

    async def async_update(self, **kwargs):
        """Run normal replay with the correct rollover date, then persist seed."""
        now = kwargs.get("now")
        if isinstance(now, datetime):
            self._midnight_rollover_now_date = now.astimezone(agile.LONDON).date()
        self._settled_midnight_seed_applied = False
        self._settled_midnight_stale_replay_soc = None
        state = await super().async_update(**kwargs)
        if self._midnight_rollover_seed_dirty:
            await self._save_midnight_rollover_seed()

        continuity = state.get("midnight_replay_continuity")
        if isinstance(continuity, dict):
            continuity["synthetic_boundary_days"] = sorted(
                self._synthetic_midnight_boundary_days
            )
            continuity["settled_rollover_seed"] = (
                dict(self._settled_midnight_rollover_seed)
                if isinstance(self._settled_midnight_rollover_seed, dict)
                else None
            )
            continuity["settled_rollover_seed_applied"] = bool(
                self._settled_midnight_seed_applied
            )
            continuity["stale_replay_ending_soc_ignored"] = (
                self._settled_midnight_stale_replay_soc
            )
            continuity["rollover_soc_authority"] = SETTLED_ROLLOVER_SOURCE
        self._state = state
        return self.state

    def reconcile_current_day_settlements(self, *, settled_half_hours, now: datetime):
        """Capture the rebuilt settled handoff while the cheap window is active."""
        state = super().reconcile_current_day_settlements(
            settled_half_hours=settled_half_hours,
            now=now,
        )
        self._capture_active_cheap_rollover_seed(now)
        return state
