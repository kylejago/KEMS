"""Persistent once-per-event financial rewards for ROI only.

This ledger cannot authorise Octopus bookings, free import or FoxESS writes.
The upstream integration does not publish per-event supplier settlement.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core.roi_reward_audit import build_reward_audit
from .kems_core.roi_rewards import date_of, number

_LONDON = ZoneInfo("Europe/London")


class ROIRewardRecorder:
    def __init__(self, hass, entry_id: str) -> None:
        self._store = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.roi_rewards"
        )
        self._happy_hours: dict[str, dict] = {}
        self._power_downs: dict[str, dict] = {}

    async def async_load(self) -> None:
        saved = await self._store.async_load() or {}
        for name, destination in (
            ("happy_hours", self._happy_hours),
            ("power_downs", self._power_downs),
        ):
            entries = saved.get(name)
            if isinstance(entries, dict):
                destination.update(
                    (str(k), v) for k, v in entries.items() if isinstance(v, dict)
                )

    async def async_observe(
        self, receipts: list, events: list, *, provisional_happy_hours=()
    ) -> None:
        changed = False
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
            if current is not None and (
                current.get("basis") == "completed_meter_and_tariff_verified_hour"
                or current.get("supplier_settled") is True
                or number(current.get("covered_minutes")) is not None
                and float(current["covered_minutes"]) > minutes
            ):
                continue
            saved = {
                "day": start_dt.astimezone(_LONDON).date().isoformat(),
                "pence": round(pence, 6),
                "supplier_settled": False,
                "basis": "provisional_partial_physical_meter_credit",
                "confidence": item.get("confidence", "low"),
                "rate_basis": item.get("rate_basis"),
                "covered_minutes": minutes,
                "coverage_percent": number(item.get("coverage_percent")),
                "observed_import_kwh": energy,
            }
            if self._happy_hours.get(key) != saved:
                self._happy_hours[key] = saved
                changed = True

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
            if self._power_downs.get(key) != saved:
                self._power_downs[key] = saved
                changed = True

        if changed:
            await self._store.async_save(
                {
                    "happy_hours": self._happy_hours,
                    "power_downs": self._power_downs,
                }
            )

    def totals(self, now: datetime, commissioned) -> dict[str, float]:
        first = commissioned.isoformat() if commissioned is not None else None
        today = now.astimezone(_LONDON).date().isoformat()

        def collect(source):
            total = daily = unsettled = 0.0
            for record in source.values():
                day, value = record.get("day"), number(record.get("pence"))
                if first is None or not isinstance(day, str) or value is None:
                    continue
                if not first <= day <= today:
                    continue
                total += value
                if day == today:
                    daily += value
                if record.get("supplier_settled") is not True:
                    unsettled += value
            return total, daily, unsettled

        hh, hd, hu = collect(self._happy_hours)
        pd, dd, pu = collect(self._power_downs)
        return {
            "happy": round(hh, 6),
            "power_down": round(pd, 6),
            "total": round(hh + pd, 6),
            "today": round(hd + dd, 6),
            "unsettled": round(hu + pu, 6),
        }

    def audit(self, now, commissioned, *, bookings=(), events=()):
        """Expose itemised ROI reward evidence without changing accounting."""
        return build_reward_audit(
            self._happy_hours,
            self._power_downs,
            bookings,
            events,
            now=now,
            commissioning_date=commissioned,
        )
