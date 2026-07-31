"""Explainable advice engine for KEMS."""

from __future__ import annotations

from .models import (
    AdviceItem,
    AdviceState,
    GasSummary,
    LearnedState,
    SimulationConfig,
    Snapshot,
)


def _item(
    code: str,
    title: str,
    message: str,
    priority: int,
    confidence: float,
    saving: float | None = None,
) -> AdviceItem:
    """Create an advice item with bounded confidence."""
    return AdviceItem(
        code=code,
        title=title,
        message=message,
        priority=priority,
        confidence=max(0.0, min(confidence, 100.0)),
        estimated_saving_pence=saving,
    )


class AdviceEngine:
    """Create recommendations from current and learned data."""

    def evaluate(
        self,
        snapshot: Snapshot,
        learned: LearnedState,
        config: SimulationConfig,
        gas: GasSummary | None = None,
    ) -> AdviceState:
        """Return ordered advice without calling any device service."""
        items: list[AdviceItem] = []
        confidence = max(learned.confidence, 20.0)

        if snapshot.current_import_rate is None:
            items.append(
                _item(
                    "waiting_for_tariff",
                    "Waiting for tariff data",
                    "KEMS needs a current Octopus import rate before it can "
                    "assess cost.",
                    100,
                    100.0,
                )
            )

        if not learned.ready:
            items.append(
                _item(
                    "learning",
                    "Learning your home",
                    f"KEMS has observed {learned.days_observed} day(s). "
                    "Advice becomes more personalised after at least seven days.",
                    35,
                    learned.confidence,
                )
            )

        if snapshot.cheap_period_confirmed:
            if snapshot.battery_soc is not None and snapshot.battery_soc < 95:
                items.append(
                    _item(
                        "charge_battery_cheap",
                        "Cheap period: battery headroom available",
                        "The tariff is cheap and the battery is below 95%. "
                        "The proposed strategy would charge it now.",
                        80,
                        confidence,
                    )
                )
            if snapshot.ev_connected is True and snapshot.ev_charging is not True:
                items.append(
                    _item(
                        "charge_ev_cheap",
                        "Cheap period: EV is connected",
                        "The EV is connected but not charging during a cheap slot.",
                        75,
                        confidence,
                    )
                )
            if not any(item.priority >= 75 for item in items):
                items.append(
                    _item(
                        "cheap_period_active",
                        "Cheap period active",
                        "This is the preferred time for flexible electricity demand.",
                        55,
                        confidence,
                    )
                )
        else:
            if (
                snapshot.grid_import_kw is not None
                and snapshot.grid_import_kw > 0.1
                and snapshot.current_import_rate is not None
            ):
                saving = snapshot.grid_import_kw * snapshot.current_import_rate
                items.append(
                    _item(
                        "day_rate_import",
                        "Day-rate grid import detected",
                        f"The home is importing {snapshot.grid_import_kw:.2f} kW "
                        "outside a cheap period.",
                        95,
                        confidence,
                        round(saving, 2),
                    )
                )

            predicted = learned.predicted_energy_until_offpeak_kwh
            if predicted is not None and snapshot.battery_soc is not None:
                usable = (
                    config.battery_capacity_kwh
                    * max(
                        snapshot.battery_soc - config.battery_reserve_percent,
                        0.0,
                    )
                    / 100
                )
                if usable + 0.25 < predicted:
                    items.append(
                        _item(
                            "battery_shortfall",
                            "Battery may not last until off-peak",
                            f"KEMS predicts about {predicted:.1f} kWh is needed before "
                            f"the next cheap period, with about {usable:.1f} kWh "
                            "usable.",
                            90,
                            learned.confidence,
                        )
                    )

            if (
                snapshot.solar_power_kw is not None
                and snapshot.house_load_kw is not None
                and snapshot.solar_power_kw > snapshot.house_load_kw + 0.25
            ):
                surplus = snapshot.solar_power_kw - snapshot.house_load_kw
                items.append(
                    _item(
                        "solar_surplus",
                        "Solar surplus available",
                        f"Solar exceeds house load by about {surplus:.2f} kW.",
                        60,
                        confidence,
                    )
                )

        if gas and gas.available:
            if (
                gas.usage_today_kwh is not None
                and gas.typical_daily_usage_kwh is not None
                and gas.typical_daily_usage_kwh > 0
                and gas.usage_today_kwh > gas.typical_daily_usage_kwh * 1.25
            ):
                items.append(
                    _item(
                        "high_gas_usage",
                        "Gas usage above the learned daily level",
                        f"Gas use is {gas.usage_today_kwh:.1f} kWh today versus a "
                        f"typical {gas.typical_daily_usage_kwh:.1f} kWh.",
                        70,
                        max(min(gas.data_coverage, 100.0), 20.0),
                    )
                )
            elif gas.cost_today_pence is not None:
                items.append(
                    _item(
                        "gas_tracking",
                        "Whole-home gas tracking active",
                        f"Gas has contributed {gas.cost_today_pence:.1f}p to today's "
                        "whole-home energy cost.",
                        25,
                        max(min(gas.data_coverage, 100.0), 20.0),
                    )
                )

        if not items:
            items.append(
                _item(
                    "observe",
                    "Monitoring normally",
                    "No urgent energy action is indicated by the current observations.",
                    10,
                    confidence,
                )
            )

        ordered = tuple(sorted(items, key=lambda advice: advice.priority, reverse=True))
        return AdviceState(primary=ordered[0], items=ordered)
