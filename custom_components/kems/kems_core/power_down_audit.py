"""Home Assistant-independent Power Down session audit and accounting helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class PowerDownAuditState:
    """Safety evidence gathered only while a Power Down session is active."""

    active_samples_observed: int = 0
    ev_successfully_blocked: bool = True
    plan_safe_throughout: bool = True
    island_override_observed: bool = False

    def observe(
        self,
        *,
        session_active: bool,
        desired_ev_charging_allowed: bool,
        plan_safe: bool,
        island_mode_active: bool,
    ) -> PowerDownAuditState:
        """Apply one controller sample, ignoring joined/pre-session observations."""
        if not session_active:
            return self
        return replace(
            self,
            active_samples_observed=self.active_samples_observed + 1,
            ev_successfully_blocked=(
                self.ev_successfully_blocked and not desired_ev_charging_allowed
            ),
            plan_safe_throughout=self.plan_safe_throughout and plan_safe,
            island_override_observed=(
                self.island_override_observed or island_mode_active
            ),
        )


@dataclass(frozen=True, slots=True)
class PowerDownAccountingState:
    """Integrated planned site flow from the final Full KEMS Agile event route."""

    planned_battery_to_home_kwh: float = 0.0
    planned_export_kwh: float = 0.0
    maximum_inverter_output_kw: float = 0.0
    rewardable_reduction_kwh: float = 0.0
    bonus_pence: float = 0.0
    fixed_export_income_pence: float = 0.0
    route_samples_observed: int = 0
    reward_samples_observed: int = 0

    def observe(
        self,
        *,
        hours: float,
        battery_to_home_kw: float,
        grid_import_kw: float,
        grid_export_kw: float,
        inverter_output_kw: float,
        baseline_net_kw: float | None,
        bonus_rate_pence: float | None,
        export_rate_pence: float,
    ) -> PowerDownAccountingState:
        """Integrate one final shadow-route interval on a net site-meter basis."""
        hours = max(float(hours), 0.0)
        if hours <= 0.0:
            return self

        battery_home = max(float(battery_to_home_kw), 0.0)
        grid_import = max(float(grid_import_kw), 0.0)
        grid_export = max(float(grid_export_kw), 0.0)
        inverter_output = max(float(inverter_output_kw), 0.0)
        export_rate = max(float(export_rate_pence), 0.0)

        rewardable = 0.0
        bonus = 0.0
        reward_samples = self.reward_samples_observed
        if baseline_net_kw is not None and bonus_rate_pence is not None:
            baseline_energy = float(baseline_net_kw) * hours
            planned_net_energy = (grid_import - grid_export) * hours
            rewardable = max(baseline_energy - planned_net_energy, 0.0)
            bonus = rewardable * max(float(bonus_rate_pence), 0.0)
            reward_samples += 1

        return replace(
            self,
            planned_battery_to_home_kwh=(
                self.planned_battery_to_home_kwh + battery_home * hours
            ),
            planned_export_kwh=self.planned_export_kwh + grid_export * hours,
            maximum_inverter_output_kw=max(
                self.maximum_inverter_output_kw,
                inverter_output,
            ),
            rewardable_reduction_kwh=(self.rewardable_reduction_kwh + rewardable),
            bonus_pence=self.bonus_pence + bonus,
            fixed_export_income_pence=(
                self.fixed_export_income_pence + grid_export * hours * export_rate
            ),
            route_samples_observed=self.route_samples_observed + 1,
            reward_samples_observed=reward_samples,
        )


def finalise_power_down_audit(
    state: PowerDownAuditState,
) -> tuple[bool | None, str]:
    """Return success/failure/inconclusive status plus an explicit reason.

    No active samples means KEMS has no evidence about what happened during the
    session. That is deliberately *inconclusive* rather than a false failure.
    """
    if state.active_samples_observed <= 0:
        return None, "insufficient_active_samples"
    if state.island_override_observed:
        return False, "island_safety_override"
    if not state.plan_safe_throughout:
        return False, "plan_safety_check_failed"
    if not state.ev_successfully_blocked:
        return False, "ev_block_check_failed"
    return True, "completed"
