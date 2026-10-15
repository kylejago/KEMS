"""Alpha9.40 Weekend Happy Hour recommendation/auto-join contracts."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.kems.happy_hour_auto_join import (
    HappyHourCandidate,
    RateSlot,
    _booking_soc,
    booked_happy_hour_matches_plan,
    _simulation_soc,
    auto_join_control_gate,
    choose_best_candidate,
    day_rate_coverage,
    score_candidate,
)
from custom_components.kems.product_types import (
    EXPORT_TARIFF_TYPE_AGILE,
    EXPORT_TARIFF_TYPE_NONE,
)

_LONDON = ZoneInfo("Europe/London")


def _half_hour_rates(
    target_day: date,
    value,
) -> list[RateSlot]:
    local_start = datetime(
        target_day.year,
        target_day.month,
        target_day.day,
        tzinfo=_LONDON,
    )
    next_day = target_day + timedelta(days=1)
    local_end = datetime(
        next_day.year,
        next_day.month,
        next_day.day,
        tzinfo=_LONDON,
    )
    cursor = local_start.astimezone(UTC)
    end = local_end.astimezone(UTC)
    output = []
    while cursor < end:
        slot_start = cursor
        slot_end = min(slot_start + timedelta(minutes=30), end)
        slot_value = value(slot_start) if callable(value) else value
        output.append(RateSlot(slot_start, slot_end, float(slot_value)))
        cursor = slot_end
    return output


def _candidate(hour: int, code: str) -> HappyHourCandidate:
    start = datetime(2026, 9, 19, hour, tzinfo=UTC)
    return HappyHourCandidate(
        code=code,
        start=start,
        end=start + timedelta(hours=1),
        availability="available",
        source="test",
        source_entity="event.octopus_energy_test_octoplus_power_up_events",
    )


def _score(
    candidate: HappyHourCandidate,
    *,
    now: datetime,
    imports: list[RateSlot],
    exports: list[RateSlot],
    export_type: str,
    soc: float = 95.0,
    max_discharge_kw: float = 7.0,
    solar_kwh: float = 12.0,
):
    result = score_candidate(
        candidate,
        now=now,
        import_rates=imports,
        export_rates=exports,
        export_tariff_type=export_type,
        fixed_export_rate_pence=12.0,
        current_soc_percent=soc,
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
        max_charge_kw=7.0,
        max_discharge_kw=max_discharge_kw,
        export_limit_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        expected_house_tomorrow_kwh=12.0,
        expected_solar_tomorrow_kwh=solar_kwh,
    )
    assert result is not None
    return result


def test_auto_join_requires_control_and_every_independent_gate() -> None:
    allowed, reasons = auto_join_control_gate(
        operating_mode="simulate",
        auto_join_enabled=True,
        control_enabled=True,
        commissioned=True,
        emergency_stop=False,
        battery_installed=True,
    )
    assert allowed is False
    assert reasons == ("operating_mode_not_control",)

    allowed, reasons = auto_join_control_gate(
        operating_mode="control",
        auto_join_enabled=False,
        control_enabled=True,
        commissioned=True,
        emergency_stop=False,
        battery_installed=True,
    )
    assert allowed is False
    assert reasons == ("auto_join_switch_off",)

    allowed, reasons = auto_join_control_gate(
        operating_mode="control",
        auto_join_enabled=True,
        control_enabled=True,
        commissioned=True,
        emergency_stop=False,
        battery_installed=True,
    )
    assert allowed is True
    assert reasons == ()


def test_no_paid_export_never_creates_headroom_by_deliberate_export() -> None:
    target_day = date(2026, 9, 19)
    imports = _half_hour_rates(target_day, 30.0)
    score = _score(
        _candidate(14, "NO-EXPORT"),
        now=datetime(2026, 9, 18, 18, tzinfo=UTC),
        imports=imports,
        exports=[],
        export_type=EXPORT_TARIFF_TYPE_NONE,
        soc=99.0,
    )
    assert score.planned_pre_event_export_kwh == 0.0
    assert score.expected_battery_free_import_kwh < 7.0


def test_lower_export_cost_wins_when_other_economics_are_equal() -> None:
    target_day = date(2026, 9, 19)
    imports = _half_hour_rates(target_day, 30.0)

    def export_value(moment: datetime) -> float:
        if 12 <= moment.hour < 13:
            return 1.0
        if 14 <= moment.hour < 15:
            return 9.0
        return 10.0

    exports = _half_hour_rates(target_day, export_value)
    now = datetime(2026, 9, 19, 0, tzinfo=UTC)
    low_export = _score(
        _candidate(12, "LOW"),
        now=now,
        imports=imports,
        exports=exports,
        export_type=EXPORT_TARIFF_TYPE_AGILE,
        soc=20.0,
    )
    high_export = _score(
        _candidate(14, "HIGH"),
        now=now,
        imports=imports,
        exports=exports,
        export_type=EXPORT_TARIFF_TYPE_AGILE,
        soc=20.0,
    )
    winner = choose_best_candidate([high_export, low_export])
    assert winner is not None
    assert winner.candidate.code == "LOW"
    assert low_export.event_export_rate_pence < high_export.event_export_rate_pence


def test_total_value_can_beat_the_lowest_export_price_heuristic() -> None:
    target_day = date(2026, 9, 19)

    def import_value(moment: datetime) -> float:
        # Expensive evening energy makes a late free refill particularly useful.
        return 60.0 if moment.hour >= 20 else 20.0

    def export_value(moment: datetime) -> float:
        if 8 <= moment.hour < 9:
            return 1.0
        if 18 <= moment.hour < 19:
            return 5.0
        return 20.0

    imports = _half_hour_rates(target_day, import_value)
    exports = _half_hour_rates(target_day, export_value)
    now = datetime(2026, 9, 19, 6, tzinfo=UTC)
    early = _score(
        _candidate(8, "EARLY-CHEAP-EXPORT"),
        now=now,
        imports=imports,
        exports=exports,
        export_type=EXPORT_TARIFF_TYPE_AGILE,
        soc=99.0,
        max_discharge_kw=0.25,
        solar_kwh=0.0,
    )
    late = _score(
        _candidate(18, "LATE-BETTER-TOTAL"),
        now=now,
        imports=imports,
        exports=exports,
        export_type=EXPORT_TARIFF_TYPE_AGILE,
        soc=99.0,
        max_discharge_kw=0.25,
        solar_kwh=0.0,
    )
    winner = choose_best_candidate([early, late])
    assert winner is not None
    assert early.event_export_rate_pence < late.event_export_rate_pence
    assert late.net_benefit_pence > early.net_benefit_pence
    assert winner.candidate.code == "LATE-BETTER-TOTAL"


def test_day_coverage_requires_most_of_the_happy_hour_day() -> None:
    target_day = date(2026, 9, 19)
    rates = _half_hour_rates(target_day, 25.0)
    assert day_rate_coverage(rates, target_day) == pytest.approx(1.0)
    assert day_rate_coverage(rates[:-4], target_day) >= 0.90
    assert day_rate_coverage(rates[:-5], target_day) < 0.90


def test_auto_join_never_invents_missing_battery_soc() -> None:
    def candidate(value: object) -> SimpleNamespace:
        return SimpleNamespace(simulation=SimpleNamespace(simulated_battery_soc=value))

    assert _simulation_soc(SimpleNamespace()) is None
    assert _simulation_soc(SimpleNamespace(simulation=None)) is None
    for value in (None, float("nan"), float("inf"), -1, 101):
        assert _simulation_soc(candidate(value)) is None
    assert _simulation_soc(candidate(80)) == 80.0
    assert _simulation_soc(candidate(0)) == 0.0


@pytest.mark.parametrize(
    "override",
    [
        {"joined_event_active": False},
        {"reward_ledger_complete": False},
        {"remaining_reward_kwh": 0.0},
        {"remaining_reward_kwh": 16.01},
        {"remaining_reward_kwh": float("nan")},
        {"battery_headroom_kwh": None},
        {"battery_headroom_kwh": 0.0},
        {"charge_target_kw": 0.0},
        {"charge_target_kw": float("inf")},
        {"power_down_active": True},
        {"grid_available": False},
        {"emergency_stop": True},
    ],
)
def test_happy_hour_charge_authority_fail_closed(override) -> None:
    from kems_core.control_write_authority import (
        assess_happy_hour_charge_authority,
    )

    evidence = {
        "joined_event_active": True,
        "reward_ledger_complete": True,
        "remaining_reward_kwh": 10.0,
        "battery_headroom_kwh": 20.0,
        "charge_target_kw": 5.0,
        "power_down_active": False,
        "grid_available": True,
        "emergency_stop": False,
    }
    assert assess_happy_hour_charge_authority(**evidence)
    evidence.update(override)
    assert not assess_happy_hour_charge_authority(**evidence)


def test_live_happy_hour_booking_requires_measured_soc() -> None:
    data = SimpleNamespace(
        simulation=SimpleNamespace(simulated_battery_soc=95),
        snapshot=SimpleNamespace(battery_soc=20),
    )
    assert _booking_soc(data, operating_mode="control") == 20.0
    assert _booking_soc(data, operating_mode="simulate") == 95.0
    data.snapshot.battery_soc = None
    assert _booking_soc(data, operating_mode="control") is None
    data.snapshot.battery_soc = 101
    assert _booking_soc(data, operating_mode="control") is None


def test_happy_hour_live_booking_must_match_active_event() -> None:
    start = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    booking = {
        "status": "booked",
        "booked_event_code": "TEST-BOOKING",
        "booked_start": start.isoformat(),
        "booked_end": end.isoformat(),
    }
    plan = {"start": start.isoformat(), "end": end.isoformat()}
    assert booked_happy_hour_matches_plan(booking, plan, start)
    assert not booked_happy_hour_matches_plan(booking, plan, end)
    assert not booked_happy_hour_matches_plan(
        booking, plan, start - timedelta(seconds=1)
    )
    assert not booked_happy_hour_matches_plan(
        booking,
        {"start": start.isoformat(), "end": (end + timedelta(hours=1)).isoformat()},
        start,
    )
    assert not booked_happy_hour_matches_plan(
        {**booking, "status": "recommended"}, plan, start
    )
    assert not booked_happy_hour_matches_plan(
        {**booking, "booked_event_code": None}, plan, start
    )
