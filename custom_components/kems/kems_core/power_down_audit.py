"""Home Assistant-independent Power Down session audit helpers."""

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


def finalise_power_down_audit(state: PowerDownAuditState) -> tuple[bool, str]:
    """Return completion status and an explicit audit reason."""
    if state.active_samples_observed <= 0:
        return False, "session_activity_not_observed"
    if state.island_override_observed:
        return False, "island_safety_override"
    if not state.plan_safe_throughout:
        return False, "plan_safety_check_failed"
    if not state.ev_successfully_blocked:
        return False, "ev_block_check_failed"
    return True, "completed"
