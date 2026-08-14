"""Predicted ROI, actual payback, and profit calculations for KEMS."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta

from .models import LifetimeLedger, ROIConfig, ROIState, SimulationState
from .system_profile import FOXHOLE_PROPOSAL_PROFILE

MAX_PAYBACK_MONTHS = 50 * 12
MIN_PREDICTION_DAYS = 7.0


def _midnight(value: date, reference: datetime) -> datetime:
    """Return local midnight for a date using the reference timezone."""
    return datetime.combine(value, time.min, tzinfo=reference.tzinfo)


def _observation_days(ledger: LifetimeLedger, now: datetime) -> int:
    """Return the inclusive number of observed calendar days."""
    if ledger.first_observation is None:
        return 0
    return max((now.date() - ledger.first_observation.date()).days + 1, 1)


def _elapsed_observation_days(ledger: LifetimeLedger, now: datetime) -> float:
    """Return complete elapsed observation time in fractional days."""
    if ledger.first_observation is None:
        return 0.0
    return max((now - ledger.first_observation).total_seconds() / 86400, 0.0)


def _expected_proposal_generation_kwh(start: datetime, end: datetime) -> float:
    """Return proposal solar expected across the exact observed time window.

    This lets ROI treat a short summer observation differently from a short
    winter observation instead of multiplying either period straight by 365.
    """
    if end <= start:
        return 0.0

    total = 0.0
    cursor = start.date()
    final_date = end.date()
    while cursor <= final_date:
        day_start = datetime.combine(cursor, time.min, tzinfo=start.tzinfo)
        day_end = day_start + timedelta(days=1)
        overlap_start = max(start, day_start)
        overlap_end = min(end, day_end)
        if overlap_end > overlap_start:
            day_seconds = max((day_end - day_start).total_seconds(), 1.0)
            overlap_fraction = (overlap_end - overlap_start).total_seconds() / day_seconds
            daily_target = (
                FOXHOLE_PROPOSAL_PROFILE.monthly_generation_kwh[cursor.month - 1]
                / monthrange(cursor.year, cursor.month)[1]
            )
            total += daily_target * overlap_fraction
        cursor += timedelta(days=1)
    return max(total, 0.0)


def _seasonally_adjusted_annual_saving(
    ledger: LifetimeLedger,
    simulation: SimulationState,
    now: datetime,
) -> float | None:
    """Project annual value without pretending every month looks like today.

    KEMS separates two evidence-backed components:

    * non-export system value (mainly avoided expensive import and event value)
      is annualised from the observed/simulated home behaviour;
    * export income is projected from the proposal's full 12-month solar shape,
      the export fraction actually seen in the simulation, and the *current*
      paid export tariff. Historical export income is deliberately excluded if
      the export tariff is currently awaiting activation.

    This remains an evidence-based projection rather than a guaranteed return.
    """
    if ledger.first_observation is None:
        return None
    elapsed_days = _elapsed_observation_days(ledger, now)
    if elapsed_days < MIN_PREDICTION_DAYS:
        return None

    total_value_gbp = ledger.simulated_system_value_pence / 100
    historical_export_gbp = ledger.simulated_export_income_pence / 100
    non_export_value_gbp = total_value_gbp - historical_export_gbp
    annual_non_export_gbp = non_export_value_gbp / elapsed_days * 365

    annual_export_gbp = 0.0
    export_rate_pence = max(float(simulation.effective_export_rate_pence or 0.0), 0.0)
    if simulation.export_tariff_active and export_rate_pence > 0.0:
        expected_observed_solar = _expected_proposal_generation_kwh(
            ledger.first_observation,
            now,
        )
        observed_simulated_solar = max(ledger.simulated_solar_generation_kwh, 0.0)
        if expected_observed_solar >= 1.0 and observed_simulated_solar >= 1.0:
            # Coverage gaps and the proposal-solar factor can move the retained
            # total slightly away from the proposal curve. Bound that evidence
            # so a short or incomplete period cannot multiply the annual model
            # to an implausible value.
            solar_scale = min(
                max(observed_simulated_solar / expected_observed_solar, 0.60),
                1.40,
            )
            projected_annual_solar = (
                FOXHOLE_PROPOSAL_PROFILE.annual_generation_kwh * solar_scale
            )
            export_fraction = min(
                max(
                    ledger.simulated_grid_export_kwh / observed_simulated_solar,
                    0.0,
                ),
                1.0,
            )
            projected_annual_export_kwh = projected_annual_solar * export_fraction
            annual_export_gbp = projected_annual_export_kwh * export_rate_pence / 100

    return annual_non_export_gbp + annual_export_gbp


def _projected_payback_months(
    investment_gbp: float,
    annual_saving_gbp: float,
    config: ROIConfig,
) -> int | None:
    """Return the month in which projected cumulative savings reach investment."""
    if investment_gbp <= 0:
        return 0
    if annual_saving_gbp <= 0:
        return None

    cumulative = 0.0
    inflation = max(config.electricity_inflation_percent, -99.0) / 100
    degradation = min(max(config.battery_degradation_percent, 0.0), 99.0) / 100

    for month in range(1, MAX_PAYBACK_MONTHS + 1):
        year_index = (month - 1) // 12
        adjusted_annual = annual_saving_gbp
        adjusted_annual *= (1 + inflation) ** year_index
        adjusted_annual *= (1 - degradation) ** year_index
        monthly_net = adjusted_annual / 12 - config.annual_maintenance_gbp / 12
        cumulative += monthly_net
        if cumulative >= investment_gbp:
            return month
    return None


def _projected_net_value(
    investment_gbp: float,
    annual_saving_gbp: float,
    config: ROIConfig,
) -> float:
    """Return discounted net value across the configured forecast horizon."""
    inflation = max(config.electricity_inflation_percent, -99.0) / 100
    degradation = min(max(config.battery_degradation_percent, 0.0), 99.0) / 100
    discount = max(config.discount_rate_percent, 0.0) / 100
    net_present_value = -investment_gbp

    for year in range(1, max(config.forecast_years, 1) + 1):
        year_index = year - 1
        saving = annual_saving_gbp
        saving *= (1 + inflation) ** year_index
        saving *= (1 - degradation) ** year_index
        net_cashflow = saving - config.annual_maintenance_gbp
        net_present_value += net_cashflow / ((1 + discount) ** year)
    return net_present_value


class ROIEngine:
    """Calculate pre-install predictions and live post-install ROI."""

    def evaluate(
        self,
        ledger: LifetimeLedger,
        simulation: SimulationState,
        now: datetime,
        config: ROIConfig,
    ) -> ROIState:
        """Return current ROI and lifetime financial state."""
        observed_days = _observation_days(ledger, now)
        elapsed_days = _elapsed_observation_days(ledger, now)
        investment = config.net_investment_gbp
        predicted_annual = _seasonally_adjusted_annual_saving(
            ledger,
            simulation,
            now,
        )

        payback_months = None
        predicted_payback_years = None
        predicted_payback_date = None
        predicted_net_value = None
        if predicted_annual is not None:
            payback_months = _projected_payback_months(
                investment,
                predicted_annual,
                config,
            )
            if payback_months is not None:
                predicted_payback_years = payback_months / 12
                predicted_payback_date = now + timedelta(days=payback_months * 30.4375)
            predicted_net_value = _projected_net_value(
                investment,
                predicted_annual,
                config,
            )

        installed = (
            config.commissioning_date is not None
            and now.date() >= config.commissioning_date
        )
        actual_value = ledger.actual_system_value_pence / 100
        operating_costs = ledger.system_operating_cost_pence / 100
        operating_costs += max(config.manual_system_costs_gbp, 0.0)
        recovered = actual_value - operating_costs
        paid_back = installed and recovered >= investment and investment > 0
        actual_roi = None
        remaining = None
        profit = None
        actual_payback_date = None
        if installed:
            actual_roi = 100.0 if investment <= 0 else 100 * recovered / investment
            remaining = max(investment - recovered, 0.0)
            profit = max(recovered - investment, 0.0)
            if ledger.paid_back_date is not None:
                actual_payback_date = _midnight(ledger.paid_back_date, now)

        if paid_back:
            status = "System paid back — profit mode"
        elif installed:
            status = "Live payback tracking"
        elif predicted_annual is not None and predicted_annual > 0:
            status = "Pre-install ROI simulation"
        else:
            status = "Learning financial baseline"

        if installed and config.commissioning_date is not None:
            operating_elapsed_days = max(
                (now.date() - config.commissioning_date).days,
                0,
            )
            confidence_days = float(operating_elapsed_days)
        else:
            confidence_days = elapsed_days
        confidence = min(max(confidence_days / 30 * 100, 0.0), 100.0)
        ready = predicted_annual is not None and elapsed_days >= MIN_PREDICTION_DAYS

        return ROIState(
            ready=ready,
            status=status,
            system_installed=installed,
            system_paid_back=paid_back,
            net_investment_gbp=round(investment, 2),
            predicted_annual_saving_gbp=(
                round(predicted_annual, 2) if predicted_annual is not None else None
            ),
            predicted_payback_years=(
                round(predicted_payback_years, 2)
                if predicted_payback_years is not None
                else None
            ),
            predicted_payback_date=predicted_payback_date,
            predicted_net_value_gbp=(
                round(predicted_net_value, 2) if predicted_net_value is not None else None
            ),
            actual_value_created_today_gbp=(
                round((simulation.actual_system_value_pence or 0.0) / 100, 2)
                if installed
                else None
            ),
            actual_value_created_total_gbp=(
                round(actual_value, 2) if installed else None
            ),
            actual_roi_percent=(
                round(actual_roi, 2) if actual_roi is not None else None
            ),
            actual_payback_remaining_gbp=(
                round(remaining, 2) if remaining is not None else None
            ),
            actual_payback_date=actual_payback_date,
            actual_net_profit_gbp=(round(profit, 2) if profit is not None else None),
            operating_costs_gbp=round(operating_costs, 2),
            confidence=round(confidence, 1),
            observed_days=observed_days,
            operating_days=ledger.system_operating_days,
        )
