"""Conservative session-local upper battery energy for Happy Hour headroom.

FoxESS only changes its integer SOC state when a whole percent changes. A raw
HA last-changed timestamp is therefore NOT a device-heartbeat deadline.
This independent ledger tracks possible charging between genuinely observed
SOC anchors; it never turns an unchanged reading into a fresh SOC report.
Missing power intervals are charged at the entire configured charging rate.
It is not an authority to operate FoxESS: existing physical/EV/DNO guards
retain all hardware control.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any


_MAX_SEED_AGE_S = 3600.0
_MAX_INTERVAL_S = 120.0
_MAX_CONTINUITY_GAP_S = 900.0
_FRESH_PHYSICAL_S = 90.0
_CHARGE_MARGIN_KW = 1.0
_ANCHOR_MARGIN_KWH = 0.5


def _n(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


class HappyHourChargeHeadroomContinuity:
    """Maintain a pessimistic *upper* stored-energy bound, never a twin SOC."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last_at: datetime | None = None
        self._anchor_at: datetime | None = None
        self._anchor_soc: float | None = None
        self._upper_kwh: float | None = None
        self._previous_charge_kw: float | None = None
        self._samples = 0
        self.status = "awaiting_verified_soc_anchor"

    def observe(
        self,
        snapshot: Any,
        *,
        now: datetime,
        capacity: float,
        max_charge: float,
        positive_is_discharge: bool,
    ) -> tuple[float | None, str]:
        """Use consecutive physical observations; never fill gaps optimistically."""
        ages = getattr(snapshot, "source_age_seconds", None)
        ages = ages if isinstance(ages, dict) else {}
        stale = set(getattr(snapshot, "stale_fields", ()) or ())
        soc = _n(getattr(snapshot, "battery_soc", None))
        soc_age = _n(ages.get("battery_soc"))
        power = _n(getattr(snapshot, "battery_power_kw", None))
        power_age = _n(ages.get("battery_power_kw"))
        timestamp = getattr(snapshot, "timestamp", None)
        grid_fresh = any(
            field not in stale
            and _n(getattr(snapshot, field, None)) is not None
            and (age := _n(ages.get(field))) is not None
            and 0.0 <= age <= _FRESH_PHYSICAL_S
            for field in ("grid_import_kw", "grid_export_kw")
        )
        house_age = _n(ages.get("house_load_kw"))
        physically_correlated = (
            grid_fresh
            and "house_load_kw" not in stale
            and _n(getattr(snapshot, "house_load_kw", None)) is not None
            and house_age is not None
            and 0.0 <= house_age <= _FRESH_PHYSICAL_S
        )
        fresh_power = (
            power is not None
            and power_age is not None
            and 0.0 <= power_age <= _FRESH_PHYSICAL_S
            and "battery_power_kw" not in stale
        )
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or abs((now - timestamp).total_seconds()) > _MAX_INTERVAL_S
            or soc is None
            or not 0.0 <= soc <= 100.0
            or soc_age is None
            or soc_age < 0.0
            or "battery_soc" in stale
            or capacity <= 0.0
            or max_charge <= 0.0
            or not physically_correlated
        ):
            self.reset()
            self.status = "missing_current_correlated_physical_telemetry"
            return None, self.status

        charge_kw = (
            max(-power if positive_is_discharge else power, 0.0)
            if fresh_power and power is not None
            else None
        )
        anchor_at = timestamp - timedelta(seconds=soc_age)

        if self._last_at is None:
            if soc_age > _MAX_SEED_AGE_S:
                self.status = "awaiting_recent_soc_anchor_for_cold_start"
                return None, self.status
            self._anchor_at = anchor_at
            self._anchor_soc = soc
            self._upper_kwh = min(
                capacity,
                capacity * soc / 100.0
                + max_charge * soc_age / 3600.0
                + _ANCHOR_MARGIN_KWH,
            )
            self._last_at = now
            self._previous_charge_kw = charge_kw
            self._samples = 1
            self.status = "anchor_seeded_waiting_continuity"
            return None, self.status

        assert self._last_at is not None
        assert self._anchor_at is not None
        assert self._anchor_soc is not None
        assert self._upper_kwh is not None
        elapsed = (now - self._last_at).total_seconds()
        if not 0.0 < elapsed <= _MAX_CONTINUITY_GAP_S:
            self.reset()
            self.status = "observation_gap_needs_new_soc_anchor"
            return None, self.status

        if anchor_at > self._anchor_at + timedelta(seconds=2.0):
            # A genuine newer SOC report re-anchors the upper bound.
            self._anchor_at = anchor_at
            self._anchor_soc = soc
            self._upper_kwh = min(
                capacity,
                capacity * soc / 100.0
                + max_charge * soc_age / 3600.0
                + _ANCHOR_MARGIN_KWH,
            )
        elif (
            anchor_at < self._anchor_at - timedelta(seconds=2.0)
            or abs(soc - self._anchor_soc) > 0.01
        ):
            self.reset()
            self.status = "soc_anchor_timestamp_or_value_conflict"
            return None, self.status
        elif (
            elapsed <= _MAX_INTERVAL_S
            and charge_kw is not None
            and self._previous_charge_kw is not None
        ):
            possible_charge_kw = (
                max(charge_kw, self._previous_charge_kw) * 1.10
                + _CHARGE_MARGIN_KW
            )
            self._upper_kwh = min(
                capacity,
                self._upper_kwh + possible_charge_kw * elapsed / 3600.0,
            )
        else:
            # No reliable recent direction sample: assume FULL charging.
            self._upper_kwh = min(
                capacity, self._upper_kwh + max_charge * elapsed / 3600.0
            )

        self._last_at = now
        self._previous_charge_kw = charge_kw
        self._samples += 1
        if not fresh_power:
            self.status = "power_unverified_worst_case_charge_debit"
            return None, self.status
        if self._samples < 2:
            self.status = "waiting_second_sample"
            return None, self.status
        self.status = "continuous_bounded_charge_headroom"
        return self._upper_kwh, self.status
