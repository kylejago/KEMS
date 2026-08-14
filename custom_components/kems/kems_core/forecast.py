"""Forecast fusion and profit-first reserve planning for KEMS."""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import (
    ForecastConfig,
    ForecastHour,
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SimulationState,
    SolarForecastState,
)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _scale_hourly_to_fused(
    now: datetime,
    hourly: tuple[ForecastHour, ...],
    expected_remaining_today_kwh: float | None,
    expected_tomorrow_kwh: float | None,
) -> tuple[ForecastHour, ...]:
    """Scale Open-Meteo's hourly shape to the fused daily energy totals."""
    if not hourly:
        return ()
    tomorrow = now.date() + timedelta(days=1)
    raw_remaining = sum(
        item.solar_energy_kwh
        for item in hourly
        if item.timestamp.date() == now.date() and item.timestamp > now
    )
    raw_tomorrow = sum(
        item.solar_energy_kwh for item in hourly if item.timestamp.date() == tomorrow
    )
    remaining_factor = (
        max(expected_remaining_today_kwh, 0.0) / raw_remaining
        if expected_remaining_today_kwh is not None and raw_remaining > 0.001
        else 1.0
    )
    tomorrow_factor = (
        max(expected_tomorrow_kwh, 0.0) / raw_tomorrow
        if expected_tomorrow_kwh is not None and raw_tomorrow > 0.001
        else 1.0
    )
    result: list[ForecastHour] = []
    for item in hourly:
        factor = 1.0
        if item.timestamp.date() == tomorrow:
            factor = tomorrow_factor
        elif item.timestamp.date() == now.date() and item.timestamp > now:
            factor = remaining_factor
        result.append(
            ForecastHour(
                timestamp=item.timestamp,
                solar_energy_kwh=round(max(item.solar_energy_kwh * factor, 0.0), 3),
                cloud_cover_percent=item.cloud_cover_percent,
                precipitation_mm=item.precipitation_mm,
            )
        )
    return tuple(result)


def fuse_solar_forecasts(
    *,
    now: datetime,
    forecast_solar_remaining_today_kwh: float | None,
    forecast_solar_tomorrow_kwh: float | None,
    forecast_solar_entity_count: int,
    open_meteo_remaining_today_kwh: float | None,
    open_meteo_tomorrow_kwh: float | None,
    hourly: tuple[ForecastHour, ...] = (),
    average_cloud_cover_tomorrow_percent: float | None = None,
    precipitation_tomorrow_mm: float | None = None,
    error: str | None = None,
) -> SolarForecastState:
    """Fuse Forecast.Solar with a deliberately conservative Open-Meteo check.

    Forecast.Solar remains the primary production estimate. Open-Meteo is used
    to add an hourly shape and to pull an optimistic Forecast.Solar total down
    when the independent irradiance forecast materially disagrees. A more
    optimistic Open-Meteo result only nudges the primary estimate upward.
    """

    fs_ready = forecast_solar_tomorrow_kwh is not None
    om_ready = open_meteo_tomorrow_kwh is not None

    expected_tomorrow: float | None = None
    expected_remaining: float | None = None
    agreement: float | None = None
    confidence = 0.0
    source = "unavailable"

    if fs_ready and om_ready:
        fs_tomorrow = max(float(forecast_solar_tomorrow_kwh), 0.0)
        om_tomorrow = max(float(open_meteo_tomorrow_kwh), 0.0)
        denominator = max(fs_tomorrow, om_tomorrow, 0.1)
        agreement = max(
            0.0,
            100.0 * (1.0 - abs(fs_tomorrow - om_tomorrow) / denominator),
        )

        if om_tomorrow < fs_tomorrow * 0.80:
            # Poor independent irradiance forecast: become meaningfully more
            # conservative, but do not discard Forecast.Solar entirely.
            expected_tomorrow = 0.60 * fs_tomorrow + 0.40 * om_tomorrow
            confidence = 70.0 if agreement >= 60.0 else 55.0
        elif om_tomorrow > fs_tomorrow * 1.20:
            # Do not increase export aggressively because one provider is sunny.
            expected_tomorrow = 0.85 * fs_tomorrow + 0.15 * om_tomorrow
            confidence = 72.0 if agreement >= 60.0 else 60.0
        else:
            expected_tomorrow = 0.75 * fs_tomorrow + 0.25 * om_tomorrow
            confidence = 90.0 if agreement >= 80.0 else 80.0

        fs_remaining = forecast_solar_remaining_today_kwh
        om_remaining = open_meteo_remaining_today_kwh
        if fs_remaining is not None and om_remaining is not None:
            fs_remaining = max(float(fs_remaining), 0.0)
            om_remaining = max(float(om_remaining), 0.0)
            if om_remaining < fs_remaining * 0.80:
                expected_remaining = 0.60 * fs_remaining + 0.40 * om_remaining
            elif om_remaining > fs_remaining * 1.20:
                expected_remaining = 0.85 * fs_remaining + 0.15 * om_remaining
            else:
                expected_remaining = 0.75 * fs_remaining + 0.25 * om_remaining
        else:
            expected_remaining = (
                max(float(fs_remaining), 0.0)
                if fs_remaining is not None
                else max(float(om_remaining), 0.0) if om_remaining is not None else None
            )
        source = "forecast_solar+open_meteo"
    elif fs_ready:
        expected_tomorrow = max(float(forecast_solar_tomorrow_kwh), 0.0)
        expected_remaining = (
            max(float(forecast_solar_remaining_today_kwh), 0.0)
            if forecast_solar_remaining_today_kwh is not None
            else None
        )
        confidence = 70.0
        source = "forecast_solar"
    elif om_ready:
        expected_tomorrow = max(float(open_meteo_tomorrow_kwh), 0.0)
        expected_remaining = (
            max(float(open_meteo_remaining_today_kwh), 0.0)
            if open_meteo_remaining_today_kwh is not None
            else None
        )
        confidence = 60.0
        source = "open_meteo"

    attribution = (
        "Weather data by Open-Meteo.com; UK Met Office data via Open-Meteo "
        "(CC BY-SA 4.0): https://open-meteo.com/"
        if om_ready
        else None
    )

    return SolarForecastState(
        ready=expected_tomorrow is not None,
        source=source,
        attribution=attribution,
        forecast_solar_available=fs_ready,
        forecast_solar_entity_count=max(int(forecast_solar_entity_count), 0),
        forecast_solar_remaining_today_kwh=(
            round(float(forecast_solar_remaining_today_kwh), 3)
            if forecast_solar_remaining_today_kwh is not None
            else None
        ),
        forecast_solar_tomorrow_kwh=(
            round(float(forecast_solar_tomorrow_kwh), 3)
            if forecast_solar_tomorrow_kwh is not None
            else None
        ),
        open_meteo_available=om_ready,
        open_meteo_remaining_today_kwh=(
            round(float(open_meteo_remaining_today_kwh), 3)
            if open_meteo_remaining_today_kwh is not None
            else None
        ),
        open_meteo_tomorrow_kwh=(
            round(float(open_meteo_tomorrow_kwh), 3)
            if open_meteo_tomorrow_kwh is not None
            else None
        ),
        expected_solar_remaining_today_kwh=(
            round(expected_remaining, 3) if expected_remaining is not None else None
        ),
        expected_solar_tomorrow_kwh=(
            round(expected_tomorrow, 3) if expected_tomorrow is not None else None
        ),
        agreement_percent=round(agreement, 1) if agreement is not None else None,
        confidence_percent=round(confidence, 1),
        average_cloud_cover_tomorrow_percent=(
            round(float(average_cloud_cover_tomorrow_percent), 1)
            if average_cloud_cover_tomorrow_percent is not None
            else None
        ),
        precipitation_tomorrow_mm=(
            round(float(precipitation_tomorrow_mm), 2)
            if precipitation_tomorrow_mm is not None
            else None
        ),
        hourly=_scale_hourly_to_fused(
            now, hourly, expected_remaining, expected_tomorrow
        ),
        last_updated=now,
        error=error,
    )


class ForecastPlanningEngine:
    """Turn a solar outlook into a minimum-intervention Full KEMS plan."""

    @staticmethod
    def _tomorrow_solar_hourly(
        forecast: SolarForecastState,
        tomorrow,
    ) -> tuple[float, ...]:
        """Aggregate fused hourly solar into 24 local-hour energy buckets."""
        buckets = [0.0] * 24
        seen = 0
        for item in forecast.hourly:
            if item.timestamp.date() != tomorrow:
                continue
            buckets[item.timestamp.hour] += max(item.solar_energy_kwh, 0.0)
            seen += 1
        return tuple(round(value, 3) for value in buckets) if seen >= 12 else ()

    @staticmethod
    def _forward_energy_day(
        *,
        starting_soc_percent: float,
        house_hourly_kwh: tuple[float, ...],
        solar_hourly_kwh: tuple[float, ...],
        capacity_kwh: float,
        reserve_percent: float,
        charge_efficiency: float,
        discharge_efficiency: float,
    ) -> tuple[float, float]:
        """Return minimum SOC and unavoidable import for a forecast day.

        This is intentionally an energy-security model rather than an inverter
        peak-power model. It asks how much stored energy is needed to avoid an
        otherwise unnecessary day-rate import. Solar is retained only when it
        is useful to cover a later forecast deficit.
        """
        reserve_kwh = capacity_kwh * reserve_percent / 100.0
        battery_kwh = _clamp(
            capacity_kwh * starting_soc_percent / 100.0,
            reserve_kwh,
            capacity_kwh,
        )
        minimum_soc = 100.0 * battery_kwh / capacity_kwh
        grid_import = 0.0
        for load, solar in zip(house_hourly_kwh, solar_hourly_kwh, strict=False):
            load = max(float(load), 0.0)
            solar = max(float(solar), 0.0)
            solar_to_home = min(load, solar)
            deficit = max(load - solar_to_home, 0.0)
            available_ac = max(battery_kwh - reserve_kwh, 0.0) * discharge_efficiency
            battery_to_home = min(deficit, available_ac)
            battery_kwh -= battery_to_home / max(discharge_efficiency, 0.01)
            grid_import += max(deficit - battery_to_home, 0.0)

            surplus = max(solar - solar_to_home, 0.0)
            charge_input = min(
                surplus,
                max(capacity_kwh - battery_kwh, 0.0) / max(charge_efficiency, 0.01),
            )
            battery_kwh += charge_input * charge_efficiency
            minimum_soc = min(minimum_soc, 100.0 * battery_kwh / capacity_kwh)
        return round(minimum_soc, 3), round(grid_import, 3)

    def _hourly_required_morning_soc(
        self,
        *,
        learned: LearnedState,
        forecast: SolarForecastState,
        now: datetime,
        capacity: float,
        reserve_percent: float,
        charge_efficiency: float,
        discharge_efficiency: float,
        safety_percent: float,
    ) -> tuple[float, float | None, float | None]:
        """Return required morning SOC plus minimum-SOC/import at that target."""
        house = learned.predicted_house_tomorrow_hourly_kwh
        solar = self._tomorrow_solar_hourly(forecast, now.date() + timedelta(days=1))
        if len(house) != 24 or len(solar) != 24:
            return 0.0, None, None

        _, import_at_full = self._forward_energy_day(
            starting_soc_percent=100.0,
            house_hourly_kwh=house,
            solar_hourly_kwh=solar,
            capacity_kwh=capacity,
            reserve_percent=reserve_percent,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
        )
        if import_at_full > 0.01:
            required = 100.0
        else:
            low = reserve_percent
            high = 100.0
            for _ in range(12):
                mid = (low + high) / 2.0
                _, predicted_import = self._forward_energy_day(
                    starting_soc_percent=mid,
                    house_hourly_kwh=house,
                    solar_hourly_kwh=solar,
                    capacity_kwh=capacity,
                    reserve_percent=reserve_percent,
                    charge_efficiency=charge_efficiency,
                    discharge_efficiency=discharge_efficiency,
                )
                if predicted_import <= 0.01:
                    high = mid
                else:
                    low = mid
            required = high
        required = _clamp(required + max(safety_percent, 0.0), reserve_percent, 100.0)
        minimum_soc, predicted_import = self._forward_energy_day(
            starting_soc_percent=required,
            house_hourly_kwh=house,
            solar_hourly_kwh=solar,
            capacity_kwh=capacity,
            reserve_percent=reserve_percent,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
        )
        return required, minimum_soc, predicted_import

    def plan(
        self,
        *,
        simulation: SimulationState,
        learned: LearnedState,
        forecast: SolarForecastState,
        simulation_config: SimulationConfig,
        forecast_config: ForecastConfig,
        cheap_window_hours: float,
    ) -> ForecastPlanState:
        """Calculate recharge feasibility, retention and solar recovery targets."""

        if not forecast_config.enabled:
            return ForecastPlanState(
                state="disabled",
                reason="Full KEMS Forecast is disabled in settings",
            )
        if not forecast.ready:
            return ForecastPlanState(
                state="unavailable",
                reason="Waiting for Forecast.Solar or Open-Meteo data",
                forecast_source=forecast.source,
                confidence_percent=forecast.confidence_percent,
            )

        capacity = max(simulation_config.battery_capacity_kwh, 0.1)
        reserve_percent = _clamp(simulation_config.battery_reserve_percent, 0.0, 100.0)
        reserve_kwh = capacity * reserve_percent / 100.0
        efficiency = max(simulation_config.discharge_efficiency, 0.01)
        charge_efficiency = max(simulation_config.charge_efficiency, 0.01)
        charge_kw = max(simulation_config.max_charge_kw, 0.0)
        safety_kwh = (
            capacity * max(forecast_config.reserve_safety_margin_percent, 0.0) / 100.0
        )

        tomorrow_house = learned.predicted_house_energy_tomorrow_kwh
        remaining_house = learned.predicted_house_energy_remaining_today_kwh
        tomorrow_solar = forecast.expected_solar_tomorrow_kwh
        remaining_solar = forecast.expected_solar_remaining_today_kwh

        if tomorrow_house is None or tomorrow_solar is None:
            return ForecastPlanState(
                state="learning",
                reason=(
                    "Solar forecast is ready but KEMS is still learning the "
                    "house-demand profile"
                ),
                forecast_source=forecast.source,
                confidence_percent=forecast.confidence_percent,
                expected_solar_remaining_today_kwh=remaining_solar,
                expected_solar_tomorrow_kwh=tomorrow_solar,
                expected_house_remaining_today_kwh=remaining_house,
                expected_house_tomorrow_kwh=tomorrow_house,
            )

        tomorrow_net_kwh = max(float(tomorrow_house) - float(tomorrow_solar), 0.0)
        hourly_required, _, _ = self._hourly_required_morning_soc(
            learned=learned,
            forecast=forecast,
            now=forecast.last_updated or datetime.now().astimezone(),
            capacity=capacity,
            reserve_percent=reserve_percent,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=efficiency,
            safety_percent=forecast_config.reserve_safety_margin_percent,
        )
        if hourly_required > 0.0:
            required_morning_soc = hourly_required
        else:
            tomorrow_required_stored_kwh = tomorrow_net_kwh / efficiency
            required_morning_stored_kwh = min(
                reserve_kwh + tomorrow_required_stored_kwh + safety_kwh,
                capacity,
            )
            required_morning_soc = 100.0 * required_morning_stored_kwh / capacity

        projected_at_cheap = simulation.projected_soc_at_cheap_period_percent
        if projected_at_cheap is None:
            projected_at_cheap = simulation.simulated_battery_soc
        if projected_at_cheap is None:
            projected_at_cheap = simulation_config.battery_initial_percent
        projected_at_cheap = _clamp(float(projected_at_cheap), reserve_percent, 100.0)

        cheap_hours = max(float(cheap_window_hours), 0.0)
        overnight_stored_kwh = charge_kw * cheap_hours * charge_efficiency
        overnight_soc_gain = 100.0 * overnight_stored_kwh / capacity
        maximum_overnight_soc = min(100.0, projected_at_cheap + overnight_soc_gain)
        full_charge_shortfall_kwh = max(
            (100.0 - maximum_overnight_soc) * capacity / 100.0, 0.0
        )
        full_charge_feasible = full_charge_shortfall_kwh <= 0.001
        additional_full_hours = (
            full_charge_shortfall_kwh / (charge_kw * charge_efficiency)
            if full_charge_shortfall_kwh > 0.001 and charge_kw > 0.0
            else 0.0
        )

        recharge_shortfall_kwh = max(
            (required_morning_soc - maximum_overnight_soc) * capacity / 100.0,
            0.0,
        )
        recharge_feasible = recharge_shortfall_kwh <= 0.001
        additional_hours = (
            recharge_shortfall_kwh / (charge_kw * charge_efficiency)
            if recharge_shortfall_kwh > 0.001 and charge_kw > 0.0
            else 0.0
        )

        minimum_precheap_soc = max(
            reserve_percent,
            required_morning_soc - overnight_soc_gain,
        )
        minimum_precheap_soc = _clamp(minimum_precheap_soc, reserve_percent, 100.0)
        retention_required = projected_at_cheap + 0.1 < minimum_precheap_soc

        house_hourly = learned.predicted_house_tomorrow_hourly_kwh
        forecast_now = forecast.last_updated or datetime.now().astimezone()
        solar_hourly = self._tomorrow_solar_hourly(
            forecast, forecast_now.date() + timedelta(days=1)
        )
        if len(house_hourly) == 24 and len(solar_hourly) == 24:
            projected_minimum_soc_tomorrow, predicted_import_tomorrow = (
                self._forward_energy_day(
                    starting_soc_percent=maximum_overnight_soc,
                    house_hourly_kwh=house_hourly,
                    solar_hourly_kwh=solar_hourly,
                    capacity_kwh=capacity,
                    reserve_percent=reserve_percent,
                    charge_efficiency=charge_efficiency,
                    discharge_efficiency=efficiency,
                )
            )
        else:
            available_tomorrow_ac_kwh = (
                max(
                    maximum_overnight_soc - reserve_percent,
                    0.0,
                )
                * capacity
                / 100.0
                * efficiency
            )
            predicted_import_tomorrow = max(
                tomorrow_net_kwh - available_tomorrow_ac_kwh, 0.0
            )
            projected_minimum_soc_tomorrow = max(
                reserve_percent,
                maximum_overnight_soc
                - (tomorrow_net_kwh / efficiency) / capacity * 100.0,
            )

        recovery_target: float | None = None
        recovery_required = False
        if remaining_house is not None and remaining_solar is not None:
            remaining_net = max(float(remaining_house) - float(remaining_solar), 0.0)
            current_required_stored = min(
                reserve_kwh + remaining_net / efficiency + safety_kwh,
                capacity,
            )
            current_required_soc = 100.0 * current_required_stored / capacity
            current_soc = simulation.simulated_battery_soc
            if current_soc is not None:
                deficit_kwh = max(
                    (current_required_soc - float(current_soc)) * capacity / 100.0,
                    0.0,
                )
                recovery_required = (
                    deficit_kwh > max(forecast_config.recovery_margin_kwh, 0.0)
                    and float(remaining_solar) > 0.05
                )
                if recovery_required:
                    recovery_target = _clamp(
                        current_required_soc, reserve_percent, 100.0
                    )

        morning_margin_kwh = (
            (maximum_overnight_soc - required_morning_soc) * capacity / 100.0
        )
        if recovery_required:
            state = "recovery"
            reason = (
                "Use available solar for the home and battery until the "
                "forecast reserve is recovered, then resume Full KEMS export "
                "behaviour"
            )
        elif retention_required:
            state = "protect"
            reason = (
                "Retain only the battery energy needed before the cheap period so the "
                "overnight window can reach tomorrow's forecast requirement"
            )
        elif morning_margin_kwh <= max(forecast_config.watch_margin_kwh, 0.0):
            state = "watch"
            reason = (
                "Tomorrow is forecast to be relatively tight, but no export "
                "restriction is required yet; KEMS will recalculate automatically"
            )
        else:
            state = "normal"
            reason = (
                "Forecast reserve is sufficient; continue normal profit-first "
                "Full KEMS export behaviour"
            )

        return ForecastPlanState(
            ready=True,
            state=state,
            reason=reason,
            forecast_source=forecast.source,
            confidence_percent=forecast.confidence_percent,
            expected_solar_remaining_today_kwh=(
                round(float(remaining_solar), 3)
                if remaining_solar is not None
                else None
            ),
            expected_solar_tomorrow_kwh=round(float(tomorrow_solar), 3),
            expected_house_remaining_today_kwh=(
                round(float(remaining_house), 3)
                if remaining_house is not None
                else None
            ),
            expected_house_tomorrow_kwh=round(float(tomorrow_house), 3),
            projected_soc_at_cheap_start_percent=round(projected_at_cheap, 1),
            cheap_window_hours=round(cheap_hours, 2),
            maximum_overnight_soc_percent=round(maximum_overnight_soc, 1),
            overnight_charge_capacity_kwh=round(overnight_stored_kwh, 3),
            full_charge_feasible=full_charge_feasible,
            additional_cheap_time_to_full_hours=round(additional_full_hours, 2),
            required_morning_soc_percent=round(required_morning_soc, 1),
            recharge_target_feasible=recharge_feasible,
            recharge_shortfall_kwh=round(recharge_shortfall_kwh, 3),
            additional_cheap_time_required_hours=round(additional_hours, 2),
            minimum_precheap_soc_percent=round(minimum_precheap_soc, 1),
            solar_recovery_target_percent=(
                round(recovery_target, 1) if recovery_target is not None else None
            ),
            projected_minimum_soc_tomorrow_percent=round(
                projected_minimum_soc_tomorrow, 1
            ),
            predicted_day_rate_import_kwh=round(predicted_import_tomorrow, 3),
            battery_retention_required=retention_required,
            solar_recovery_required=recovery_required,
        )
