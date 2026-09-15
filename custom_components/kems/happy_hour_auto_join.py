"""Safe Octopus Weekend Happy Hour recommendation and automatic joining.

Alpha9.40 extends the existing joined-event Happy Hour planner with a separate
booking authority.  Available Octopus slots are scored the night before using
published Agile rates and a conservative battery counterfactual.  Recommendation
runs in every KEMS simulation/control mode, while the external Octopus join
service is hard-gated behind Control mode, commissioning, master control and an
explicit opt-in switch that defaults off.

The existing Happy Hour runtime remains the dispatch authority after a booking:
it creates economically useful battery headroom, blocks deliberate export during
the reward hour and enforces the independent 16 kWh-per-reward-hour ledgers.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .product_types import (
    EXPORT_TARIFF_TYPE_AGILE,
    EXPORT_TARIFF_TYPE_FIXED,
    EXPORT_TARIFF_TYPE_NONE,
    export_tariff_type_from_options,
)

LOGGER = logging.getLogger(__name__)

CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED = "happy_hour_auto_join_enabled"
HAPPY_HOUR_AUTO_JOIN_STORAGE_VERSION = 1
HAPPY_HOUR_PRICE_COVERAGE_REQUIRED = 0.90
HAPPY_HOUR_JOIN_RETRY_COOLDOWN = timedelta(minutes=30)
HAPPY_HOUR_REWARD_CAP_KWH_PER_HOUR = 16.0
HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY = 2
HAPPY_HOUR_COORDINATOR_SESSIONS_PER_REWARD = 2
_LONDON = ZoneInfo("Europe/London")
_POWER_UP_SUFFIX = "_octoplus_power_up_events"
_WEEKEND_HAPPY_HOURS_SUFFIX = "_octoplus_weekend_happy_hours"
_RATE_SUFFIXES = ("_current_day_rates", "_next_day_rates")
_MODEL = "alpha9.40_conservative_counterfactual_v1"
_CONTROLLERS: dict[tuple[int, str], HappyHourAutoJoinController] = {}


@dataclass(frozen=True, slots=True)
class HappyHourCandidate:
    """One joinable Octopus Weekend Happy Hour window."""

    code: str
    start: datetime
    end: datetime
    availability: str
    source: str
    source_entity: str | None = None

    @property
    def duration_hours(self) -> float:
        return max((self.end - self.start).total_seconds() / 3600.0, 0.0)


@dataclass(frozen=True, slots=True)
class RateSlot:
    """One published half-hour electricity rate."""

    start: datetime
    end: datetime
    value_pence: float


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Transparent economic estimate for one Happy Hour candidate."""

    candidate: HappyHourCandidate
    net_benefit_pence: float
    event_import_rate_pence: float
    event_export_rate_pence: float
    future_import_value_pence: float
    pre_event_export_rate_pence: float
    expected_house_free_import_kwh: float
    expected_battery_free_import_kwh: float
    expected_battery_delivered_kwh: float
    planned_pre_event_export_kwh: float
    expected_solar_opportunity_kwh: float
    free_house_value_pence: float
    free_battery_value_pence: float
    pre_event_export_value_pence: float
    solar_opportunity_cost_pence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_code": self.candidate.code,
            "start": self.candidate.start.isoformat(),
            "end": self.candidate.end.isoformat(),
            "availability": self.candidate.availability,
            "source": self.candidate.source,
            "net_benefit_pence": round(self.net_benefit_pence, 2),
            "event_import_rate_pence": round(self.event_import_rate_pence, 4),
            "event_export_rate_pence": round(self.event_export_rate_pence, 4),
            "future_import_value_pence": round(self.future_import_value_pence, 4),
            "pre_event_export_rate_pence": round(self.pre_event_export_rate_pence, 4),
            "expected_house_free_import_kwh": round(
                self.expected_house_free_import_kwh, 3
            ),
            "expected_battery_free_import_kwh": round(
                self.expected_battery_free_import_kwh, 3
            ),
            "expected_battery_delivered_kwh": round(
                self.expected_battery_delivered_kwh, 3
            ),
            "planned_pre_event_export_kwh": round(self.planned_pre_event_export_kwh, 3),
            "expected_solar_opportunity_kwh": round(
                self.expected_solar_opportunity_kwh, 3
            ),
            "free_house_value_pence": round(self.free_house_value_pence, 2),
            "free_battery_value_pence": round(self.free_battery_value_pence, 2),
            "pre_event_export_value_pence": round(self.pre_event_export_value_pence, 2),
            "solar_opportunity_cost_pence": round(self.solar_opportunity_cost_pence, 2),
            "model": _MODEL,
        }


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalise_candidate(
    raw: Any, *, source: str, source_entity: str | None = None
) -> HappyHourCandidate | None:
    code = str(_field(raw, "code", "") or "").strip()
    start = _dt(_field(raw, "start"))
    end = _dt(_field(raw, "end"))
    availability = str(_field(raw, "availability", "available") or "available")
    if not code or start is None or end is None or end <= start:
        return None
    duration = (end - start).total_seconds() / 60.0
    if not 55.0 <= duration <= 125.0:
        return None
    if start.astimezone(_LONDON).weekday() < 5:
        return None
    if availability.strip().lower() == "full":
        return None
    return HappyHourCandidate(
        code=code,
        start=start,
        end=end,
        availability=availability,
        source=source,
        source_entity=source_entity,
    )


def _state_attributes(state: Any) -> Mapping[str, Any]:
    attributes = getattr(state, "attributes", None)
    return attributes if isinstance(attributes, Mapping) else {}


def _public_power_up_sources(hass: Any) -> list[Any]:
    states = getattr(getattr(hass, "states", None), "async_all", None)
    if not callable(states):
        return []
    try:
        all_states = list(states())
    except (TypeError, RuntimeError):
        return []
    return [
        state
        for state in all_states
        if str(getattr(state, "entity_id", ""))
        .lower()
        .startswith("event.octopus_energy_")
        and str(getattr(state, "entity_id", "")).lower().endswith(_POWER_UP_SUFFIX)
    ]


def _normalise_coordinator_happy_hour_count(value: Any) -> int | None:
    """Convert Octopus coordinator progress units into earned one-hour rewards.

    Octopus Energy 19.1 exposes ``weekend_happy_hours`` on the coordinator in
    Power Down-success units, while its public Weekend Happy Hours sensor divides
    that value by two. Mirror the integration's public entity semantics so KEMS
    never displays or plans against double the customer's banked reward balance.
    """
    raw = _number(value)
    if raw is None:
        return None
    return max(int(raw / HAPPY_HOUR_COORDINATOR_SESSIONS_PER_REWARD), 0)


def _event_day_redeemable_reward_hours(balance: int | None) -> int | None:
    """Return the reward hours KEMS may consume on one Weekend Happy Hour day."""
    if balance is None:
        return None
    return min(max(int(balance), 0), HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY)


def _reward_hours_for_candidate(candidate: HappyHourCandidate) -> int:
    """Canonicalise one Octopus reward choice to one or two one-hour rewards."""
    reward_hours = 2 if candidate.duration_hours >= 1.5 else 1
    return min(reward_hours, HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY)


def _weekend_happy_hour_count(hass: Any) -> int | None:
    states = getattr(getattr(hass, "states", None), "async_all", None)
    if callable(states):
        try:
            matches = [
                state
                for state in states()
                if str(getattr(state, "entity_id", ""))
                .lower()
                .startswith("sensor.octopus_energy_")
                and str(getattr(state, "entity_id", ""))
                .lower()
                .endswith(_WEEKEND_HAPPY_HOURS_SUFFIX)
            ]
        except (TypeError, RuntimeError):
            matches = []
        if len(matches) == 1:
            value = _number(getattr(matches[0], "state", None))
            if value is not None:
                return max(int(value), 0)

    domain_data = getattr(hass, "data", {}).get("octopus_energy", {})
    if not isinstance(domain_data, Mapping):
        return None
    counts: list[int] = []
    for account_data in domain_data.values():
        if not isinstance(account_data, Mapping):
            continue
        coordinator = account_data.get("POWER_UP_DOWN_COORDINATOR")
        data = getattr(coordinator, "data", None)
        value = _normalise_coordinator_happy_hour_count(
            getattr(data, "weekend_happy_hours", None)
        )
        if value is not None:
            counts.append(value)
    return counts[0] if len(counts) == 1 else None


def discover_available_happy_hours(
    hass: Any, *, now: datetime
) -> tuple[list[HappyHourCandidate], dict[str, Any]]:
    """Discover available HH choices without mutating Octopus state."""
    now_utc = now.astimezone(UTC)
    public_sources = _public_power_up_sources(hass)
    source_entity = (
        str(getattr(public_sources[0], "entity_id", ""))
        if len(public_sources) == 1
        else None
    )
    raw: list[Any] = []
    source = "unavailable"
    if len(public_sources) == 1:
        attrs = _state_attributes(public_sources[0])
        values = attrs.get("available_events")
        if isinstance(values, list):
            raw = list(values)
            source = "public_event_entity"

    coordinator_count: int | None = None
    coordinator_raw_count: int | None = None
    if not raw:
        domain_data = getattr(hass, "data", {}).get("octopus_energy", {})
        coordinator_matches = []
        if isinstance(domain_data, Mapping):
            for account_id, account_data in domain_data.items():
                if not isinstance(account_data, Mapping):
                    continue
                coordinator = account_data.get("POWER_UP_DOWN_COORDINATOR")
                data = getattr(coordinator, "data", None)
                values = getattr(data, "available_power_up_events", None)
                if isinstance(values, list):
                    coordinator_matches.append((str(account_id), data, values))
        if len(coordinator_matches) == 1:
            _, data, values = coordinator_matches[0]
            raw = list(values)
            source = "octopus_coordinator"
            raw_count = _number(getattr(data, "weekend_happy_hours", None))
            coordinator_raw_count = (
                max(int(raw_count), 0) if raw_count is not None else None
            )
            coordinator_count = _normalise_coordinator_happy_hour_count(raw_count)

    count = coordinator_count
    if count is None:
        count = _weekend_happy_hour_count(hass)

    candidates: list[HappyHourCandidate] = []
    for item in raw:
        candidate = _normalise_candidate(
            item,
            source=source,
            source_entity=source_entity,
        )
        if candidate is not None and candidate.start > now_utc:
            candidates.append(candidate)
    candidates.sort(key=lambda item: item.start)

    # The Power Up feed can contain non-Happy-Hour sessions. The dedicated
    # 19.1+ count is the conservative discriminator for automatic booking.
    if count is not None and count <= 0:
        candidates = []
    if count is not None and count > 0 and len(candidates) > count:
        # Keep all choices for recommendation because Octopus can expose more
        # candidate windows than the number of rewards the customer may book.
        pass

    return candidates, {
        "source": source,
        "source_entity": source_entity,
        "public_source_count": len(public_sources),
        "weekend_happy_hours_available": count,
        "weekend_happy_hours_raw_coordinator": coordinator_raw_count,
        "weekend_happy_hours_event_day_limit": (HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY),
        "weekend_happy_hours_redeemable_event_day": (
            _event_day_redeemable_reward_hours(count)
        ),
        "weekend_happy_hours_balance_basis": (
            "octopus public reward count"
            if coordinator_raw_count is None
            else "octopus coordinator progress / 2"
        ),
        "service_target_available": bool(source_entity),
    }


def _normalise_rate(raw: Any) -> RateSlot | None:
    start = _dt(_field(raw, "start"))
    end = _dt(_field(raw, "end"))
    value = _number(_field(raw, "value_inc_vat"))
    if start is None or end is None or end <= start or value is None:
        return None
    return RateSlot(start=start, end=end, value_pence=value)


def discover_octopus_rates(hass: Any) -> tuple[list[RateSlot], list[RateSlot]]:
    """Read current/next-day import and export rates from public Octopus events."""
    states = getattr(getattr(hass, "states", None), "async_all", None)
    if not callable(states):
        return [], []
    try:
        all_states = list(states())
    except (TypeError, RuntimeError):
        return [], []
    imports: list[RateSlot] = []
    exports: list[RateSlot] = []
    for state in all_states:
        entity_id = str(getattr(state, "entity_id", "")).lower()
        if not entity_id.startswith("event.octopus_energy_electricity_"):
            continue
        if not entity_id.endswith(_RATE_SUFFIXES):
            continue
        attrs = _state_attributes(state)
        raw_rates = attrs.get("rates")
        if not isinstance(raw_rates, list):
            continue
        target = exports if "_export_" in entity_id else imports
        for raw in raw_rates:
            rate = _normalise_rate(raw)
            if rate is not None:
                target.append(rate)
    return _dedupe_rates(imports), _dedupe_rates(exports)


def _dedupe_rates(rates: Iterable[RateSlot]) -> list[RateSlot]:
    values: dict[tuple[datetime, datetime], RateSlot] = {}
    for rate in rates:
        values[(rate.start, rate.end)] = rate
    return sorted(values.values(), key=lambda item: item.start)


def _overlap_hours(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    return max(
        (min(a_end, b_end) - max(a_start, b_start)).total_seconds() / 3600.0,
        0.0,
    )


def weighted_rate(
    rates: Iterable[RateSlot], start: datetime, end: datetime
) -> float | None:
    numerator = 0.0
    hours = 0.0
    for rate in rates:
        overlap = _overlap_hours(rate.start, rate.end, start, end)
        if overlap <= 0:
            continue
        numerator += rate.value_pence * overlap
        hours += overlap
    return numerator / hours if hours > 1e-9 else None


def _top_quartile_rate(
    rates: Iterable[RateSlot], start: datetime, end: datetime
) -> float | None:
    weighted: list[tuple[float, float]] = []
    for rate in rates:
        overlap = _overlap_hours(rate.start, rate.end, start, end)
        if overlap > 0:
            weighted.append((rate.value_pence, overlap))
    if not weighted:
        return None
    weighted.sort(key=lambda item: item[0], reverse=True)
    total_hours = sum(hours for _, hours in weighted)
    target_hours = max(total_hours * 0.25, min(0.5, total_hours))
    used = 0.0
    value = 0.0
    for rate, hours in weighted:
        take = min(hours, max(target_hours - used, 0.0))
        value += rate * take
        used += take
        if used >= target_hours - 1e-9:
            break
    return value / used if used > 1e-9 else None


def day_rate_coverage(rates: Iterable[RateSlot], target_day: date) -> float:
    """Return fractional local-day coverage, correctly handling BST/DST days."""
    local_start = datetime.combine(target_day, datetime.min.time(), tzinfo=_LONDON)
    local_end = datetime.combine(
        target_day + timedelta(days=1), datetime.min.time(), tzinfo=_LONDON
    )
    start = local_start.astimezone(UTC)
    end = local_end.astimezone(UTC)
    expected = max((end - start).total_seconds() / 3600.0, 0.1)
    intervals: list[tuple[datetime, datetime]] = []
    for rate in rates:
        clipped_start = max(start, rate.start)
        clipped_end = min(end, rate.end)
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end))
    if not intervals:
        return 0.0
    intervals.sort()
    merged: list[tuple[datetime, datetime]] = []
    for interval in intervals:
        if not merged or interval[0] > merged[-1][1]:
            merged.append(interval)
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], interval[1]))
    covered = sum((end_ - start_).total_seconds() for start_, end_ in merged) / 3600.0
    return min(max(covered / expected, 0.0), 1.0)


def _local_day_end(moment: datetime) -> datetime:
    local = moment.astimezone(_LONDON)
    return datetime.combine(
        local.date() + timedelta(days=1), datetime.min.time(), tzinfo=_LONDON
    ).astimezone(UTC)


def score_candidate(
    candidate: HappyHourCandidate,
    *,
    now: datetime,
    import_rates: list[RateSlot],
    export_rates: list[RateSlot],
    export_tariff_type: str,
    fixed_export_rate_pence: float,
    current_soc_percent: float,
    battery_capacity_kwh: float,
    battery_reserve_percent: float,
    max_charge_kw: float,
    max_discharge_kw: float,
    export_limit_kw: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    expected_house_tomorrow_kwh: float | None,
    expected_solar_tomorrow_kwh: float | None,
) -> CandidateScore | None:
    """Estimate incremental whole-plan value of booking one reward window."""
    event_import = weighted_rate(import_rates, candidate.start, candidate.end)
    if event_import is None:
        return None
    day_end = _local_day_end(candidate.start)
    future_import = _top_quartile_rate(import_rates, candidate.end, day_end)
    if future_import is None:
        future_import = event_import

    paid_export = export_tariff_type != EXPORT_TARIFF_TYPE_NONE
    if export_tariff_type == EXPORT_TARIFF_TYPE_AGILE:
        event_export = weighted_rate(export_rates, candidate.start, candidate.end)
        pre_export_rate = _top_quartile_rate(export_rates, now, candidate.start)
        if event_export is None or pre_export_rate is None:
            return None
    elif export_tariff_type == EXPORT_TARIFF_TYPE_FIXED:
        event_export = max(fixed_export_rate_pence, 0.0)
        pre_export_rate = max(fixed_export_rate_pence, 0.0)
    else:
        event_export = 0.0
        pre_export_rate = 0.0

    duration = float(_reward_hours_for_candidate(candidate))
    cap = HAPPY_HOUR_REWARD_CAP_KWH_PER_HOUR * duration
    house_daily = max(expected_house_tomorrow_kwh or 0.0, 0.0)
    house_free = min(house_daily / 24.0 * duration, cap)
    solar_daily = max(expected_solar_tomorrow_kwh or 0.0, 0.0)
    solar_opportunity = min(
        solar_daily / 24.0 * duration, max(export_limit_kw, 0.0) * duration
    )

    capacity = max(battery_capacity_kwh, 0.1)
    soc = min(max(current_soc_percent, 0.0), 100.0)
    reserve = min(max(battery_reserve_percent, 0.0), 100.0)
    charge_eff = min(max(charge_efficiency, 0.01), 1.0)
    discharge_eff = min(max(discharge_efficiency, 0.01), 1.0)
    headroom_stored = capacity * (100.0 - soc) / 100.0
    exportable_stored = capacity * max(soc - reserve, 0.0) / 100.0
    battery_input_power_cap = max(max_charge_kw, 0.0) * duration
    reward_battery_cap = max(cap - house_free, 0.0)

    base_input_headroom = headroom_stored / charge_eff
    desired_extra_input = max(
        min(battery_input_power_cap, reward_battery_cap) - base_input_headroom, 0.0
    )
    desired_extra_stored = desired_extra_input * charge_eff
    desired_export_ac = desired_extra_stored * discharge_eff
    hours_to_event = max((candidate.start - now).total_seconds() / 3600.0, 0.0)
    pre_export = 0.0
    if paid_export:
        pre_export = min(
            desired_export_ac,
            exportable_stored * discharge_eff,
            max(max_discharge_kw, 0.0) * hours_to_event,
            max(export_limit_kw, 0.0) * hours_to_event,
        )

    total_headroom_stored = headroom_stored + pre_export / discharge_eff
    battery_free_input = min(
        battery_input_power_cap,
        reward_battery_cap,
        total_headroom_stored / charge_eff,
    )
    delivered_later = battery_free_input * charge_eff * discharge_eff

    free_house_value = house_free * max(event_import, 0.0)
    free_battery_value = delivered_later * max(future_import, 0.0)
    pre_export_value = pre_export * max(pre_export_rate, 0.0)
    solar_opportunity_cost = solar_opportunity * max(event_export, 0.0)
    net = (
        free_house_value
        + free_battery_value
        + pre_export_value
        - solar_opportunity_cost
    )
    return CandidateScore(
        candidate=candidate,
        net_benefit_pence=net,
        event_import_rate_pence=event_import,
        event_export_rate_pence=event_export,
        future_import_value_pence=future_import,
        pre_event_export_rate_pence=pre_export_rate,
        expected_house_free_import_kwh=house_free,
        expected_battery_free_import_kwh=battery_free_input,
        expected_battery_delivered_kwh=delivered_later,
        planned_pre_event_export_kwh=pre_export,
        expected_solar_opportunity_kwh=solar_opportunity,
        free_house_value_pence=free_house_value,
        free_battery_value_pence=free_battery_value,
        pre_event_export_value_pence=pre_export_value,
        solar_opportunity_cost_pence=solar_opportunity_cost,
    )


def choose_best_candidate(scores: Iterable[CandidateScore]) -> CandidateScore | None:
    """Choose maximum net value, then lower event export cost, then earlier slot."""
    values = list(scores)
    if not values:
        return None
    return sorted(
        values,
        key=lambda item: (
            -item.net_benefit_pence,
            item.event_export_rate_pence,
            item.candidate.start,
        ),
    )[0]


def auto_join_control_gate(
    *,
    operating_mode: str,
    auto_join_enabled: bool,
    control_enabled: bool,
    commissioned: bool,
    emergency_stop: bool,
    battery_installed: bool,
) -> tuple[bool, tuple[str, ...]]:
    """Return explicit external-booking authority and all blocking reasons."""
    reasons: list[str] = []
    if str(operating_mode) != "control":
        reasons.append("operating_mode_not_control")
    if not auto_join_enabled:
        reasons.append("auto_join_switch_off")
    if not control_enabled:
        reasons.append("master_control_disabled")
    if not commissioned:
        reasons.append("system_not_commissioned")
    if emergency_stop:
        reasons.append("emergency_stop")
    if not battery_installed:
        reasons.append("battery_not_installed")
    return not reasons, tuple(reasons)


def _forecast_value(data: Any, name: str) -> float | None:
    plan = getattr(data, "forecast_plan", None)
    return _number(getattr(plan, name, None))


def _simulation_soc(data: Any) -> float:
    simulation = getattr(data, "simulation", None)
    value = _number(getattr(simulation, "simulated_battery_soc", None))
    return min(max(value if value is not None else 50.0, 0.0), 100.0)


def _iso_or_none(value: Any) -> datetime | None:
    return _dt(value)


class HappyHourAutoJoinController:
    """Per-entry recommendation, persistence and fail-closed booking authority."""

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self.entry = coordinator.entry
        self._store = Store(
            self.hass,
            HAPPY_HOUR_AUTO_JOIN_STORAGE_VERSION,
            f"{DOMAIN}.{self.entry.entry_id}.{STORAGE_NAMESPACE}.happy_hour_auto_join",
        )
        self._loaded = False
        self._persisted: dict[str, Any] = {}
        self.state: dict[str, Any] = {
            "status": "starting",
            "auto_join_enabled": False,
            "external_join_authority": False,
            "model": _MODEL,
        }

    async def async_load(self) -> None:
        if self._loaded:
            return
        stored = await self._store.async_load()
        self._persisted = dict(stored) if isinstance(stored, Mapping) else {}
        self._loaded = True

    async def _async_save(self) -> None:
        await self._store.async_save(dict(self._persisted))

    def _stored_booking_active(self, now: datetime) -> bool:
        end = _iso_or_none(self._persisted.get("booked_end"))
        return bool(
            self._persisted.get("booked_event_code")
            and end is not None
            and now <= end + timedelta(hours=1)
        )

    def _base_state(self, now: datetime) -> dict[str, Any]:
        options = self.entry.options
        control = self.coordinator.settings.control
        enabled = bool(options.get(CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED, False))
        return {
            "status": "evaluating",
            "auto_join_enabled": enabled,
            "operating_mode": str(control.operating_mode),
            "commissioned": bool(control.commissioned),
            "master_control_enabled": bool(control.control_enabled),
            "emergency_stop": bool(control.emergency_stop),
            "battery_installed": bool(options.get("battery_installed", False)),
            "external_join_authority": False,
            "decision_policy": "night_before_after_90_percent_price_coverage",
            "price_coverage_required_percent": int(
                HAPPY_HOUR_PRICE_COVERAGE_REQUIRED * 100
            ),
            "evaluated_at": now.isoformat(),
            "model": _MODEL,
            "billing_note": (
                "Happy Hour value is modelled as an expected Octopus credit; "
                "meter/import billing remains unchanged until Octopus settles it."
            ),
        }

    async def async_update(self, data: Any) -> None:
        await self.async_load()
        now = datetime.now(UTC)
        state = self._base_state(now)

        candidates, discovery = discover_available_happy_hours(self.hass, now=now)
        state.update(discovery)
        state["candidate_count"] = len(candidates)
        state["candidates"] = [
            {
                "event_code": item.code,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
                "availability": item.availability,
            }
            for item in candidates
        ]

        if self._stored_booking_active(now):
            state.update(
                {
                    "status": "booked",
                    "booked_event_code": self._persisted.get("booked_event_code"),
                    "booked_start": self._persisted.get("booked_start"),
                    "booked_end": self._persisted.get("booked_end"),
                    "booked_at": self._persisted.get("booked_at"),
                    "recommendation": self._persisted.get("recommendation"),
                }
            )
            self.state = state
            return

        if not candidates:
            state["status"] = "no_available_happy_hour_slots"
            self.state = state
            return

        local_today = now.astimezone(_LONDON).date()
        decision_day = local_today + timedelta(days=1)
        tomorrow = [
            item
            for item in candidates
            if item.start.astimezone(_LONDON).date() == decision_day
        ]
        if not tomorrow:
            next_day = min(item.start.astimezone(_LONDON).date() for item in candidates)
            state.update(
                {
                    "status": "waiting_for_night_before",
                    "next_candidate_day": next_day.isoformat(),
                }
            )
            self.state = state
            return

        import_rates, export_rates = discover_octopus_rates(self.hass)
        import_coverage = day_rate_coverage(import_rates, decision_day)
        export_type = export_tariff_type_from_options(self.entry.options)
        export_coverage = (
            day_rate_coverage(export_rates, decision_day)
            if export_type == EXPORT_TARIFF_TYPE_AGILE
            else 1.0
        )
        state.update(
            {
                "target_day": decision_day.isoformat(),
                "import_price_coverage_percent": round(import_coverage * 100.0, 1),
                "export_price_coverage_percent": round(export_coverage * 100.0, 1),
                "export_tariff_type": export_type,
            }
        )
        if (
            import_coverage < HAPPY_HOUR_PRICE_COVERAGE_REQUIRED
            or export_coverage < HAPPY_HOUR_PRICE_COVERAGE_REQUIRED
        ):
            state["status"] = "waiting_for_agile_prices"
            self.state = state
            return

        config = self.coordinator.settings.simulation
        scores: list[CandidateScore] = []
        for candidate in tomorrow:
            score = score_candidate(
                candidate,
                now=now,
                import_rates=import_rates,
                export_rates=export_rates,
                export_tariff_type=export_type,
                fixed_export_rate_pence=float(config.export_rate_pence),
                current_soc_percent=_simulation_soc(data),
                battery_capacity_kwh=float(config.battery_capacity_kwh),
                battery_reserve_percent=float(config.battery_reserve_percent),
                max_charge_kw=float(config.max_charge_kw),
                max_discharge_kw=float(config.max_discharge_kw),
                export_limit_kw=float(config.export_limit_kw),
                charge_efficiency=float(config.charge_efficiency),
                discharge_efficiency=float(config.discharge_efficiency),
                expected_house_tomorrow_kwh=_forecast_value(
                    data, "expected_house_tomorrow_kwh"
                ),
                expected_solar_tomorrow_kwh=_forecast_value(
                    data, "expected_solar_tomorrow_kwh"
                ),
            )
            if score is not None:
                scores.append(score)
        best = choose_best_candidate(scores)
        state["evaluated_candidates"] = [item.to_dict() for item in scores]
        if best is None:
            state["status"] = "insufficient_candidate_price_data"
            self.state = state
            return

        recommendation = best.to_dict()
        state.update(
            {
                "recommendation": recommendation,
                "recommended_event_code": best.candidate.code,
                "recommended_start": best.candidate.start.isoformat(),
                "recommended_end": best.candidate.end.isoformat(),
                "estimated_net_benefit_pence": round(best.net_benefit_pence, 2),
                "estimated_free_import_kwh": round(
                    best.expected_house_free_import_kwh
                    + best.expected_battery_free_import_kwh,
                    3,
                ),
                "planned_pre_event_export_kwh": round(
                    best.planned_pre_event_export_kwh, 3
                ),
                "recommendation_status": (
                    "recommended" if best.net_benefit_pence > 0 else "not_economic"
                ),
            }
        )
        if best.net_benefit_pence <= 0:
            state["status"] = "no_economic_happy_hour"
            self.state = state
            return

        control = self.coordinator.settings.control
        auto_enabled = bool(
            self.entry.options.get(CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED, False)
        )
        control_gate, gate_reasons = auto_join_control_gate(
            operating_mode=str(control.operating_mode),
            auto_join_enabled=auto_enabled,
            control_enabled=bool(control.control_enabled),
            commissioned=bool(control.commissioned),
            emergency_stop=bool(control.emergency_stop),
            battery_installed=bool(self.entry.options.get("battery_installed", False)),
        )
        if "operating_mode_not_control" in gate_reasons:
            state.update(
                {
                    "status": "would_join_simulation",
                    "would_auto_join": True,
                    "join_block_reason": "operating_mode_not_control",
                }
            )
            self.state = state
            return
        if "auto_join_switch_off" in gate_reasons:
            state.update(
                {
                    "status": "recommended_auto_join_off",
                    "would_auto_join": True,
                    "join_block_reason": "auto_join_switch_off",
                }
            )
            self.state = state
            return
        if not control_gate:
            state.update(
                {
                    "status": "join_safety_gate_blocked",
                    "would_auto_join": True,
                    "join_block_reason": ",".join(gate_reasons) or "control_gate",
                }
            )
            self.state = state
            return
        if not best.candidate.source_entity:
            state.update(
                {
                    "status": "join_service_target_unavailable",
                    "would_auto_join": True,
                    "join_block_reason": (
                        "Enable the Octopus Energy Octoplus Power Up Events entity "
                        "so KEMS can use the supported join service."
                    ),
                }
            )
            self.state = state
            return

        services = getattr(self.hass, "services", None)
        has_service = getattr(services, "has_service", None)
        if callable(has_service) and not has_service(
            "octopus_energy", "join_octoplus_weekend_happy_hour_event"
        ):
            state.update(
                {
                    "status": "join_service_unavailable",
                    "join_block_reason": "Octopus Energy 19.1+ join service unavailable",
                }
            )
            self.state = state
            return

        last_attempt = _iso_or_none(self._persisted.get("last_attempt_at"))
        if (
            self._persisted.get("last_attempt_event_code") == best.candidate.code
            and last_attempt is not None
            and now - last_attempt < HAPPY_HOUR_JOIN_RETRY_COOLDOWN
        ):
            state.update(
                {
                    "status": "join_retry_cooldown",
                    "last_attempt_at": last_attempt.isoformat(),
                }
            )
            self.state = state
            return

        self._persisted.update(
            {
                "last_attempt_event_code": best.candidate.code,
                "last_attempt_at": now.isoformat(),
                "recommendation": recommendation,
            }
        )
        await self._async_save()
        state["status"] = "joining"
        state["external_join_authority"] = True
        self.state = state

        try:
            response = await services.async_call(
                "octopus_energy",
                "join_octoplus_weekend_happy_hour_event",
                {
                    "entity_id": best.candidate.source_entity,
                    "event_code": best.candidate.code,
                },
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # service owns validation/failure detail
            LOGGER.warning("KEMS Happy Hour auto-join failed safely: %s", err)
            state.update(
                {
                    "status": "join_failed",
                    "external_join_authority": False,
                    "last_join_error": str(err),
                }
            )
            self.state = state
            return

        if not isinstance(response, Mapping) or response.get("success") is not True:
            state.update(
                {
                    "status": "join_unconfirmed",
                    "external_join_authority": False,
                    "last_join_response": (
                        dict(response) if isinstance(response, Mapping) else None
                    ),
                }
            )
            self.state = state
            return

        booked_at = datetime.now(UTC)
        self._persisted.update(
            {
                "booked_event_code": best.candidate.code,
                "booked_start": best.candidate.start.isoformat(),
                "booked_end": best.candidate.end.isoformat(),
                "booked_at": booked_at.isoformat(),
                "recommendation": recommendation,
            }
        )
        await self._async_save()
        state.update(
            {
                "status": "booked",
                "external_join_authority": False,
                "booked_event_code": best.candidate.code,
                "booked_start": best.candidate.start.isoformat(),
                "booked_end": best.candidate.end.isoformat(),
                "booked_at": booked_at.isoformat(),
            }
        )
        self.state = state


def _controller_key(coordinator: Any) -> tuple[int, str]:
    return id(coordinator.hass), str(coordinator.entry.entry_id)


def _controller_for(coordinator: Any) -> HappyHourAutoJoinController:
    key = _controller_key(coordinator)
    controller = _CONTROLLERS.get(key)
    if controller is None:
        controller = HappyHourAutoJoinController(coordinator)
        _CONTROLLERS[key] = controller
    return controller


def happy_hour_auto_join_state(coordinator: Any) -> dict[str, Any]:
    controller = _CONTROLLERS.get(_controller_key(coordinator))
    if controller is None:
        return {
            "status": "waiting_for_first_planner_update",
            "auto_join_enabled": bool(
                coordinator.entry.options.get(CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED, False)
            ),
            "external_join_authority": False,
            "model": _MODEL,
        }
    return dict(controller.state)


def _install_dashboard_card() -> None:
    try:
        from . import happy_hour_auto
    except ImportError:
        return
    marker = "          - switch.kems_weekend_happy_hour_planning\n"
    addition = marker + "          - switch.kems_weekend_happy_hour_auto_join\n"
    if (
        "switch.kems_weekend_happy_hour_auto_join"
        not in happy_hour_auto._AUTO_DASHBOARD_INSERT
    ):
        happy_hour_auto._AUTO_DASHBOARD_INSERT = (
            happy_hour_auto._AUTO_DASHBOARD_INSERT.replace(marker, addition)
        )

    auto_line = (
        "**Automatic source:** {{ auto or 'waiting for Octopus Power Up data' }}"
    )
    planner_lines = """**Automatic source:** {{ auto or 'waiting for Octopus Power Up data' }}  
          **Auto join:** {{ states('switch.kems_weekend_happy_hour_auto_join') }}  
          **Booking status:** {{ state_attr('switch.kems_weekend_happy_hour_auto_join', 'status') or 'waiting' }}  
          **Recommended start:** {{ state_attr('switch.kems_weekend_happy_hour_auto_join', 'recommended_start') or '—' }}  
          **Expected benefit:** {{ state_attr('switch.kems_weekend_happy_hour_auto_join', 'estimated_net_benefit_pence') or 0 }} p  
          **Agile coverage:** {{ state_attr('switch.kems_weekend_happy_hour_auto_join', 'import_price_coverage_percent') or 0 }}%"""
    if "**Booking status:**" not in happy_hour_auto._AUTO_DASHBOARD_INSERT:
        happy_hour_auto._AUTO_DASHBOARD_INSERT = (
            happy_hour_auto._AUTO_DASHBOARD_INSERT.replace(auto_line, planner_lines)
        )


def install_happy_hour_auto_join() -> None:
    """Install the planner around coordinator updates without owning dispatch."""
    from .coordinator import KEMSCoordinator

    original = KEMSCoordinator._async_update_data
    if getattr(original, "_kems_happy_hour_auto_join", False):
        _install_dashboard_card()
        return

    async def wrapped(self):
        data = await original(self)
        controller = _controller_for(self)
        try:
            await controller.async_update(data)
        except Exception as err:  # planner must never take KEMS offline
            LOGGER.exception("Happy Hour auto-join planner failed safely")
            controller.state = {
                "status": "planner_error",
                "auto_join_enabled": bool(
                    self.entry.options.get(CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED, False)
                ),
                "external_join_authority": False,
                "error": str(err),
                "model": _MODEL,
            }
        return data

    wrapped._kems_happy_hour_auto_join = True
    KEMSCoordinator._async_update_data = wrapped
    _install_dashboard_card()
