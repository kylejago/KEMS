"""Alpha 7.31 solar-aware inverter headroom for Agile dispatch.

The first genuine Alpha7.28 non-zero export candidate exposed a real shared-AC
constraint: a 7 kW battery export target was requested while proposal solar was
already occupying part of the 7 kW inverter output. The independent 13-point
validator correctly rejected that command.

Alpha7.31 moves that constraint into the optimiser-facing dispatch target. When
the battery is discharging, Feed-in First routes available solar to AC first,
solar-to-battery becomes zero, and battery discharge receives only the inverter
headroom that remains. The same routing basis is then used by the shadow
candidate and Alpha7.30 current-routing snapshot.

This remains simulation/shadow only. Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_alpha723_shadow as alpha723
from . import agile_alpha730_current_routing as alpha730
from . import agile_rolling_replan as rolling
from .kems_core import ControlConfig, ControlState, SimulationConfig, SimulationState

_EPSILON = 1e-6
_OLD_POWER_BASIS = (
    "**Power basis:** one current KEMS coordinator routing snapshot. The proposal "
    "digital twin supplies current solar/routing context and the exact Agile rolling "
    "battery candidate is substituted before grid/export totals are shown."
)
_NEW_POWER_BASIS = (
    "**Power basis:** one current KEMS coordinator routing snapshot. During battery "
    "discharge, proposal/live solar is routed to AC first and the battery receives "
    "only the remaining inverter headroom; solar-to-battery is zero for that "
    "candidate snapshot."
)


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _proposal_solar_evidence(self, config: SimulationConfig) -> dict[str, Any]:
    """Return current proposal/live solar available to the shared AC inverter."""
    records = list(getattr(self, "_panel_today_records", []) or [])
    if not records:
        return {
            "available": False,
            "reason": "current KEMS snapshot unavailable",
        }

    current = records[-1]
    simulator = getattr(self, "_simulation", None)
    solar: float | None = None
    basis = "unavailable"
    if simulator is not None and hasattr(simulator, "_simulated_solar_power"):
        try:
            solar = float(simulator._simulated_solar_power(current, config))
            basis = "same proposal/live solar path as Agile replay"
        except (TypeError, ValueError):
            solar = None
    if solar is None:
        solar = _number(getattr(current, "solar_power_kw", None))
        if solar is not None:
            basis = "current mapped solar power"
    if solar is None:
        return {
            "available": False,
            "reason": "current proposal/live solar power unavailable",
        }

    solar = max(solar, 0.0)
    inverter_limit = max(config.inverter_limit_kw, 0.0)
    routed_solar_ac = min(solar, inverter_limit)
    return {
        "available": True,
        "basis": basis,
        "solar_generation_kw": round(solar, 3),
        "routed_solar_ac_kw": round(routed_solar_ac, 3),
        "solar_curtailment_kw": round(max(solar - routed_solar_ac, 0.0), 3),
        "inverter_limit_kw": round(inverter_limit, 3),
    }


def _dispatch_targets_with_solar_headroom(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now,
    config: SimulationConfig,
    tariff,
) -> dict[str, Any]:
    """Cap battery discharge before shadow construction using solar AC headroom."""
    targets = alpha731_original_dispatch_targets(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    requested_house = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
    requested_export = max(
        _number(targets.get("battery_export_target_kw")) or 0.0,
        0.0,
    )
    requested_total = max(
        _number(targets.get("battery_discharge_target_kw")) or 0.0,
        0.0,
    )

    if requested_total <= _EPSILON:
        evidence = {
            "active": False,
            "reason": "battery discharge is not active",
            "requested_battery_to_home_kw": round(requested_house, 3),
            "requested_battery_export_kw": round(requested_export, 3),
            "requested_total_discharge_kw": round(requested_total, 3),
        }
        self._kems_alpha731_solar_headroom = evidence
        targets["solar_aware_inverter_headroom"] = evidence
        return targets

    solar = _proposal_solar_evidence(self, config)
    if not solar.get("available"):
        evidence = {
            "active": False,
            "reason": solar.get("reason"),
            "requested_battery_to_home_kw": round(requested_house, 3),
            "requested_battery_export_kw": round(requested_export, 3),
            "requested_total_discharge_kw": round(requested_total, 3),
        }
        self._kems_alpha731_solar_headroom = evidence
        targets["solar_aware_inverter_headroom"] = evidence
        return targets

    routed_solar_ac = max(_number(solar.get("routed_solar_ac_kw")) or 0.0, 0.0)
    inverter_headroom = max(config.inverter_limit_kw - routed_solar_ac, 0.0)
    battery_headroom = min(
        max(config.max_discharge_kw, 0.0),
        inverter_headroom,
    )
    permitted_house = min(requested_house, battery_headroom)
    remaining = max(battery_headroom - permitted_house, 0.0)
    permitted_export = min(
        requested_export,
        remaining,
        max(config.export_limit_kw, 0.0),
    )
    permitted_total = permitted_house + permitted_export

    evidence = {
        "active": True,
        "basis": "Feed-in First solar AC before battery discharge",
        **solar,
        "battery_inverter_headroom_kw": round(battery_headroom, 3),
        "requested_battery_to_home_kw": round(requested_house, 3),
        "requested_battery_export_kw": round(requested_export, 3),
        "requested_total_discharge_kw": round(requested_total, 3),
        "permitted_battery_to_home_kw": round(permitted_house, 3),
        "permitted_battery_export_kw": round(permitted_export, 3),
        "permitted_total_discharge_kw": round(permitted_total, 3),
        "solar_to_battery_kw_while_discharging": 0.0,
        "target_was_reduced": bool(
            abs(permitted_house - requested_house) > _EPSILON
            or abs(permitted_export - requested_export) > _EPSILON
            or abs(permitted_total - requested_total) > _EPSILON
        ),
    }
    self._kems_alpha731_solar_headroom = evidence
    targets.update(
        {
            "house_battery_kw": round(permitted_house, 3),
            "battery_export_target_kw": round(permitted_export, 3),
            "battery_discharge_target_kw": round(permitted_total, 3),
            "solar_aware_inverter_headroom": evidence,
        }
    )
    return targets


def _rolling_plan_with_solar_headroom_evidence(
    self,
    state: dict[str, Any],
    *,
    now,
    config: SimulationConfig,
    tariff,
) -> dict[str, Any]:
    """Attach the final solar-aware headroom evidence to the rolling plan."""
    plan = alpha731_original_rolling_plan(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(plan, dict):
        return plan
    evidence = getattr(self, "_kems_alpha731_solar_headroom", None)
    if isinstance(evidence, dict):
        plan["solar_aware_inverter_headroom"] = dict(evidence)
        plan["solar_aware_inverter_headroom_active"] = bool(evidence.get("active"))
        plan["solar_routed_ac_kw"] = evidence.get("routed_solar_ac_kw")
        plan["battery_inverter_headroom_kw"] = evidence.get(
            "battery_inverter_headroom_kw"
        )
        plan["solar_aware_requested_battery_export_kw"] = evidence.get(
            "requested_battery_export_kw"
        )
        plan["solar_aware_permitted_battery_export_kw"] = evidence.get(
            "permitted_battery_export_kw"
        )
    return plan


def _build_shadow_with_solar_aware_ac(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
):
    """Make candidate AC accounting match Feed-in First discharge routing."""
    candidate, context = alpha731_original_build_shadow(
        control,
        simulation,
        config,
        agile_state,
    )
    if candidate is None:
        return None, context

    candidate_discharge = max(
        _number(candidate.desired_total_discharge_power_kw) or 0.0,
        0.0,
    )
    if candidate_discharge <= _EPSILON:
        return candidate, context

    solar = max(_number(simulation.current_simulated_solar_power_kw) or 0.0, 0.0)
    routed_solar_ac = min(solar, max(config.inverter_limit_kw, 0.0))
    routing = dict(context.get("outcome_routing") or {})
    base_discharge = max(
        _number(routing.get("base_digital_twin_discharge_kw"))
        or (
            (_number(routing.get("battery_to_home_kw")) or 0.0)
            + (_number(routing.get("battery_export_kw")) or 0.0)
        ),
        0.0,
    )
    replay_base_ac = routed_solar_ac + base_discharge
    candidate_ac = routed_solar_ac + candidate_discharge

    candidate = replace(
        candidate,
        total_kh7_ac_output_kw=round(candidate_ac, 3),
        kh7_output_headroom_kw=round(
            max(config.inverter_limit_kw - candidate_ac, 0.0),
            3,
        ),
    )
    routing.update(
        {
            "basis": "solar_aware_feed_in_first_ac_substitute_candidate_discharge",
            "solar_to_battery_kw": 0.0,
            "routed_solar_ac_kw": round(routed_solar_ac, 3),
            "total_kh7_ac_output_kw": round(replay_base_ac, 3),
            "base_digital_twin_discharge_kw": round(base_discharge, 3),
            "candidate_discharge_kw": round(candidate_discharge, 3),
            "normalised_candidate_ac_output_kw": round(candidate_ac, 3),
            "solar_to_ac_policy": "Feed-in First during battery discharge",
        }
    )
    context = {
        **context,
        "outcome_routing": routing,
        "solar_aware_inverter_headroom": {
            "routed_solar_ac_kw": round(routed_solar_ac, 3),
            "battery_inverter_headroom_kw": round(
                max(config.inverter_limit_kw - routed_solar_ac, 0.0),
                3,
            ),
            "candidate_discharge_kw": round(candidate_discharge, 3),
            "candidate_kh7_ac_output_kw": round(candidate_ac, 3),
            "solar_to_battery_kw_while_discharging": 0.0,
        },
    }
    return candidate, context


def _snapshot_with_solar_aware_routing(
    self,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Make Alpha7.30 display the same physically executable candidate routing."""
    snapshot = alpha731_original_current_snapshot(self, state)
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return snapshot

    total_discharge = max(_number(snapshot.get("total_discharge_kw")) or 0.0, 0.0)
    if total_discharge <= _EPSILON:
        snapshot["solar_aware_discharge_routing"] = False
        return snapshot

    config = getattr(self, "_rolling_config", None)
    if not isinstance(config, SimulationConfig):
        return snapshot

    solar_generation = max(_number(snapshot.get("solar_power_kw")) or 0.0, 0.0)
    routed_solar_ac = min(solar_generation, max(config.inverter_limit_kw, 0.0))
    house = max(_number(snapshot.get("simulated_house_load_kw")) or 0.0, 0.0)
    battery_home = max(_number(snapshot.get("battery_to_home_kw")) or 0.0, 0.0)
    battery_export = max(_number(snapshot.get("battery_export_kw")) or 0.0, 0.0)
    solar_to_home = min(house, routed_solar_ac)
    solar_export = max(routed_solar_ac - solar_to_home, 0.0)
    grid_import = max(house - solar_to_home - battery_home, 0.0)
    grid_export = solar_export + battery_export
    kh7_ac = routed_solar_ac + total_discharge

    snapshot.update(
        {
            "routing_basis": (
                "current coordinator routing snapshot — solar-aware Feed-in First"
            ),
            "solar_to_battery_kw": 0.0,
            "solar_to_home_kw": round(solar_to_home, 3),
            "solar_export_kw": round(solar_export, 3),
            "grid_to_battery_kw": 0.0,
            "grid_import_kw": round(grid_import, 3),
            "grid_export_kw": round(grid_export, 3),
            "normalised_kh7_ac_output_kw": round(kh7_ac, 3),
            "solar_curtailment_kw": round(
                max(solar_generation - routed_solar_ac, 0.0),
                3,
            ),
            "solar_routing_basis": (
                "Feed-in First: solar to AC first; battery uses remaining "
                "inverter headroom"
            ),
            "solar_aware_discharge_routing": True,
        }
    )
    return snapshot


def _patch_alpha730_power_basis() -> None:
    """Keep the dashboard explanation aligned with the Alpha7.31 routing model."""
    card = alpha730._CURRENT_ROUTING_CARD
    if _OLD_POWER_BASIS in card:
        alpha730._CURRENT_ROUTING_CARD = card.replace(
            _OLD_POWER_BASIS,
            _NEW_POWER_BASIS,
            1,
        )


def install_alpha731_solar_headroom_patch() -> None:
    """Install solar-aware target, shadow, replay-input and display parity."""
    dispatch = alpha717._dispatch_targets
    if not getattr(dispatch, "_kems_alpha731_solar_headroom", False):
        global alpha731_original_dispatch_targets
        alpha731_original_dispatch_targets = dispatch
        _dispatch_targets_with_solar_headroom._kems_alpha731_solar_headroom = True
        alpha717._dispatch_targets = _dispatch_targets_with_solar_headroom

    rolling_plan = rolling._rolling_plan
    if not getattr(rolling_plan, "_kems_alpha731_solar_headroom", False):
        global alpha731_original_rolling_plan
        alpha731_original_rolling_plan = rolling_plan
        _rolling_plan_with_solar_headroom_evidence._kems_alpha731_solar_headroom = True
        rolling._rolling_plan = _rolling_plan_with_solar_headroom_evidence

    build_shadow = alpha723.build_agile_shadow_command
    if not getattr(build_shadow, "_kems_alpha731_solar_headroom", False):
        global alpha731_original_build_shadow
        alpha731_original_build_shadow = build_shadow
        _build_shadow_with_solar_aware_ac._kems_alpha731_solar_headroom = True
        alpha723.build_agile_shadow_command = _build_shadow_with_solar_aware_ac

    current_snapshot = alpha730._snapshot
    if not getattr(current_snapshot, "_kems_alpha731_solar_headroom", False):
        global alpha731_original_current_snapshot
        alpha731_original_current_snapshot = current_snapshot
        _snapshot_with_solar_aware_routing._kems_alpha731_solar_headroom = True
        alpha730._snapshot = _snapshot_with_solar_aware_routing

    _patch_alpha730_power_basis()
