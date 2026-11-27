"""Persistent once-per-event financial rewards for ROI only.

This ledger cannot authorise Octopus bookings, free import or FoxESS writes.
Confirmed awards are point entitlements, not proof of cash redemption.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.power_down_awards import (
    FILE_NAME,
    apply_imported_awards,
    award_window,
    read_awards,
    reconcile_window_aliases,
)
from .kems_core.roi_reward_audit import build_reward_audit
from .kems_core.roi_rewards import date_of, number

_LONDON = ZoneInfo("Europe/London")
_LOGGER = logging.getLogger(__name__)


class ROIRewardRecorder:
    def __init__(self, hass, entry_id: str) -> None:
        self._hass = hass
        self._local_power_down_awards = []
        self._store = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.roi_rewards"
        )
        self._happy_hours: dict[str, dict] = {}
        self._power_downs: dict[str, dict] = {}
        # Historical joined-event proof is financial-only, never live booking
        # authority, and survives upstream feed retention expiry.
        self._joined_happy_hours: dict[str, dict] = {}

    async def async_load(self) -> None:
        saved = await self._store.async_load() or {}
        for name, destination in (
            ("happy_hours", self._happy_hours),
            ("power_downs", self._power_downs),
            ("joined_happy_hours", self._joined_happy_hours),
        ):
            entries = saved.get(name)
            if isinstance(entries, dict):
                destination.update(
                    (str(k), v) for k, v in entries.items() if isinstance(v, dict)
                )

        try:
            self._local_power_down_awards = await self._hass.async_add_executor_job(
                read_awards, Path(self._hass.config.path(FILE_NAME))
            )
        except (OSError, ValueError, TypeError):
            _LOGGER.warning("KEMS local Power Down awards not accepted")

    async def async_observe(
        self,
        receipts: list,
        events: list,
        *,
        provisional_happy_hours=(),
        historical_bookings=(),
        supplier_power_down_events=(),
        late_power_down_estimates=(),
        now=None,
    ) -> None:
        changed = False
        for item in historical_bookings:
            if (
                not isinstance(item, dict)
                or item.get("booking_source") != "octopus_joined_events"
            ):
                continue
            try:
                start = datetime.fromisoformat(str(item.get("start")))
                end = datetime.fromisoformat(str(item.get("end")))
            except (TypeError, ValueError):
                continue
            if (
                start.tzinfo is None
                or end.tzinfo is None
                or not 55 <= (end - start).total_seconds() / 60 <= 65
            ):
                continue
            key = f"{start.isoformat()}|{end.isoformat()}"
            proof = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "event_id": str(item.get("event_id") or "") or None,
                "booking_source": "octopus_joined_events",
            }
            if self._joined_happy_hours.get(key) != proof:
                self._joined_happy_hours[key] = proof
                changed = True
        for item in receipts:
            if not isinstance(item, dict) or item.get("completed") is not True:
                continue
            start, end = item.get("start"), item.get("end")
            try:
                start_dt = datetime.fromisoformat(str(start))
                end_dt = datetime.fromisoformat(str(end))
            except (TypeError, ValueError):
                continue
            kwh = number(item.get("import_kwh"))
            rate = number(item.get("rate_pence"))
            credit = number(item.get("credit_pence"))
            if (
                start_dt.tzinfo is None
                or end_dt.tzinfo is None
                or not 55 <= (end_dt - start_dt).total_seconds() / 60 <= 65
                or kwh is None
                or kwh > 16
                or rate is None
                or credit is None
                or credit > kwh * rate + 0.05
            ):
                continue
            key = f"{start_dt.isoformat()}|{end_dt.isoformat()}"
            saved = {
                "day": start_dt.astimezone(_LONDON).date().isoformat(),
                "pence": round(credit, 6),
                "supplier_settled": False,
                "basis": "completed_meter_and_tariff_verified_hour",
                "confidence": "meter_supported",
                "coverage_percent": 100.0,
                "covered_minutes": 60.0,
                "observed_import_kwh": kwh,
                "rate_basis": "captured_with_verified_hour",
            }
            if self._happy_hours.get(key) != saved:
                self._happy_hours[key] = saved
                changed = True

        # A partial, physically witnessed hour may contribute provisional
        # value before supplier settlement. It must never displace an existing
        # complete receipt or be multiplied out over missing meter intervals.
        for item in provisional_happy_hours:
            if not isinstance(item, dict):
                continue
            start, end = item.get("start"), item.get("end")
            try:
                start_dt = datetime.fromisoformat(str(start))
                end_dt = datetime.fromisoformat(str(end))
            except (TypeError, ValueError):
                continue
            pence = number(item.get("credit_pence"))
            energy = number(item.get("import_kwh"))
            minutes = number(item.get("covered_minutes"))
            if (
                start_dt.tzinfo is None
                or end_dt.tzinfo is None
                or not 55 <= (end_dt - start_dt).total_seconds() / 60 <= 65
                or pence is None
                or energy is None
                or not 0 < energy <= 16
                or minutes is None
                or minutes < 10
                or minutes > 60
                or pence > energy * 200 + 0.05
            ):
                continue
            key = f"{start_dt.isoformat()}|{end_dt.isoformat()}"
            current = self._happy_hours.get(key)
            historical = (
                item.get("basis") == "provisional_historical_five_minute_meter_credit"
            )
            if current is not None and (
                current.get("basis") == "completed_meter_and_tariff_verified_hour"
                or current.get("supplier_settled") is True
                or historical
                and current.get("basis") == "provisional_partial_physical_meter_credit"
                or (
                    current.get("basis") == item.get("basis")
                    and number(current.get("covered_minutes")) is not None
                    and float(current["covered_minutes"]) > minutes
                )
            ):
                continue
            saved = {
                "day": start_dt.astimezone(_LONDON).date().isoformat(),
                "pence": round(pence, 6),
                "supplier_settled": False,
                "basis": (
                    "provisional_historical_five_minute_meter_credit"
                    if historical
                    else "provisional_partial_physical_meter_credit"
                ),
                "confidence": item.get("confidence", "low"),
                "rate_basis": item.get("rate_basis"),
                "covered_minutes": minutes,
                "coverage_percent": number(item.get("coverage_percent")),
                "observed_import_kwh": energy,
            }
            if self._happy_hours.get(key) != saved:
                self._happy_hours[key] = saved
                changed = True

        changed |= reconcile_window_aliases(self._power_downs, events)
        for event in events:
            if not event or not getattr(event, "session_id", None):
                continue
            bonus = number(getattr(event, "bonus_pence", None))
            reduced = number(getattr(event, "rewardable_reduction_kwh", None))
            end = getattr(event, "session_end", None)
            if (
                event.completed_successfully is not True
                or event.physical_export_verified is not True
                or bonus is None
                or bonus <= 0
                or reduced is None
                or reduced <= 0
                or date_of(end) is None
            ):
                continue
            saved = {
                "day": date_of(end),
                "pence": round(bonus, 6),
                "supplier_settled": False,
                "basis": "meter_supported_modelled_power_down_bonus",
            }
            key = str(event.session_id)
            # The supplier's later awarded points replace this estimate.
            # Repeated scans must never downgrade a settled award.
            previous = self._power_downs.get(key, {})
            if (
                previous.get("supplier_settled") is True
                or previous.get("basis")
                == "meter_supported_supplier_interval_power_down_bonus"
            ):
                continue
            if self._power_downs.get(key) != saved:
                self._power_downs[key] = saved
                changed = True

        # Joined Octopus Power Down events can retain a later supplier award.
        # Match immutable event identity AND window against KEMS' event.
        # Never turn a pending/absent award into 0.
        known_events = {
            str(event.session_id): event
            for event in events
            if event is not None and getattr(event, "session_id", None)
        }
        # Complete supplier half-hours improve a provisional physical estimate.
        # Never override a confirmed award, or include ordinary export income.
        for item in late_power_down_estimates:
            if not isinstance(item, dict):
                continue
            key = str(item.get("session_id") or "")
            event = known_events.get(key)
            previous = self._power_downs.get(key, {})
            window = award_window(item.get("session_start"), item.get("session_end"))
            if (
                window is None
                or event is None
                or getattr(event, "completed_successfully", None) is not True
                or getattr(event, "physical_export_verified", None) is not True
                or previous.get("supplier_settled") is True
                or window != award_window(event.session_start, event.session_end)
            ):
                continue
            bonus = number(item.get("estimated_bonus_pence"))
            if (
                item.get("status") != "unsettled_event_estimate"
                or item.get("reward_calculation_basis")
                != "complete_half_hour_baselines_and_supplier_meter"
                or bonus is None
            ):
                if (
                    previous.get("basis")
                    == "meter_supported_supplier_interval_power_down_bonus"
                ):
                    del self._power_downs[key]
                    changed = True
                continue
            saved = {
                "day": date_of(event.session_end),
                "start": event.session_start.isoformat(),
                "end": event.session_end.isoformat(),
                "pence": round(bonus, 6),
                "supplier_settled": False,
                "basis": "meter_supported_supplier_interval_power_down_bonus",
            }
            if previous != saved:
                self._power_downs[key] = saved
                changed = True

        for item in supplier_power_down_events:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id") or "")
            event = known_events.get(event_id)
            # A supplier-confirmed award is financial evidence, not proof
            # of successful KEMS dispatch.
            if not event_id:
                continue
            points = item.get("rewarded_octopoints")
            if (
                not isinstance(points, int)
                or isinstance(points, bool)
                or not 0 < points <= 2_000_000
            ):
                continue
            try:
                joined_start = datetime.fromisoformat(str(item.get("start")))
                joined_end = datetime.fromisoformat(str(item.get("end")))
            except (ValueError, TypeError):
                continue
            window = award_window(joined_start, joined_end)
            if window is None or (now is not None and joined_end > now):
                continue
            if event is not None:
                if window != award_window(event.session_start, event.session_end):
                    continue
            else:
                # The configured provider may know joined events that KEMS
                # never witnessed. Only accept them with a completed exact
                # window, no competing event ID and no ambiguous legacy row.
                if now is None or any(
                    window == award_window(
                        other.session_start, other.session_end
                    )
                    for other in known_events.values()
                ):
                    continue
                alias = f"octopus-window:{window[0]}|{window[1]}"
                if any(
                    key not in (event_id, alias)
                    and (
                        award_window(receipt.get("start"), receipt.get("end"))
                        == window
                        or (
                            receipt.get("day") == date_of(joined_end)
                            and award_window(
                                receipt.get("start"), receipt.get("end")
                            )
                            is None
                        )
                    )
                    for key, receipt in self._power_downs.items()
                ):
                    continue
            previous = self._power_downs.get(event_id, {})
            previous_window = award_window(previous.get("start"), previous.get("end"))
            if previous_window is not None and previous_window != window:
                continue
            if previous and previous.get("day") != date_of(joined_end):
                continue
            event_start, event_end = joined_start, joined_end
            # Octopus publishes 800 points = £1 = 100 pence.
            saved = {
                "day": date_of(event_end),
                "pence": round(points / 8.0, 6),
                "supplier_settled": True,
                "basis": "supplier_awarded_octopoints",
                "start": event_start.astimezone(UTC).isoformat(),
                "end": event_end.astimezone(UTC).isoformat(),
                "award_source": "octopus_joined_events",
                "awarded_octopoints": points,
            }
            # An account-history-only event may later acquire its provider ID.
            # Migrate rather than count the same session twice.
            alias = f"octopus-window:{window[0]}|{window[1]}"
            if alias in self._power_downs:
                del self._power_downs[alias]
                changed = True
            if self._power_downs.get(event_id) != saved:
                self._power_downs[event_id] = saved
                changed = True

        changed |= apply_imported_awards(
            self._power_downs,
            events,
            getattr(self, "_local_power_down_awards", ()),
            now=now or datetime.now(UTC),
        )
        if changed:
            await self._store.async_save(
                {
                    "happy_hours": self._happy_hours,
                    "power_downs": self._power_downs,
                    "joined_happy_hours": self._joined_happy_hours,
                }
            )

    def totals(self, now: datetime, commissioned) -> dict[str, float]:
        first = commissioned.isoformat() if commissioned is not None else None
        today = now.astimezone(_LONDON).date().isoformat()

        def collect(source):
            total = daily = unsettled = provisional = awarded = 0.0
            for record in source.values():
                day, value = record.get("day"), number(record.get("pence"))
                if first is None or not isinstance(day, str) or value is None:
                    continue
                if not first <= day <= today:
                    continue
                total += value
                if str(record.get("basis") or "").startswith("provisional_"):
                    provisional += value
                if (
                    record.get("supplier_settled") is True
                    and record.get("basis") == "supplier_awarded_octopoints"
                ):
                    awarded += value
                if day == today:
                    daily += value
                if record.get("supplier_settled") is not True:
                    unsettled += value
            return total, daily, unsettled, provisional, awarded

        hh, hd, hu, hp, ha = collect(self._happy_hours)
        pd, dd, pu, pp, pa = collect(self._power_downs)
        return {
            "happy": round(hh, 6),
            "power_down": round(pd, 6),
            "total": round(hh + pd, 6),
            "today": round(hd + dd, 6),
            "unsettled": round(hu + pu, 6),
            "provisional": round(hp + pp, 6),
            "meter_supported": round(hh + pd - hp - pp - ha - pa, 6),
            "supplier_awarded": round(ha + pa, 6),
        }

    def audit(self, now, commissioned, *, bookings=(), events=()):
        """Expose itemised ROI reward evidence without changing accounting."""
        return build_reward_audit(
            self._happy_hours,
            self._power_downs,
            [*self._joined_happy_hours.values(), *bookings],
            events,
            now=now,
            commissioning_date=commissioned,
        )
