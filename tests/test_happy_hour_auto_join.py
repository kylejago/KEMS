"""Alpha9.40 Weekend Happy Hour recommendation/auto-join contracts."""

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.kems.happy_hour_auto_join import (
    HappyHourCandidate,
    RateSlot,
    auto_join_control_gate,
    choose_best_candidate,
    day_rate_coverage,
    score_candidate,
)
from custom_components.kems.product_types import (
    EXPORT_TARIFF_TYPE_AGILE,
    EXPORT_TARIFF_TYPE_NONE,
)


def _half_hour_rates(
    target_day: date,
    value,
) -> list[RateSlot]:
    start = datetime(target_day.year, target_day.month, target_day.day, tzinfo=UTC)
    output = []
    for index in range(48):
        slot_start = start + timedelta(minutes=30 * index)
        slot_end = slot_start + timedelta(minutes=30)
        slot_value = value(slot_start) if callable(value) else value
        output.append(RateSlot(slot_start, slot_end, float(slot_value)))
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
