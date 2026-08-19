"""Alpha 7.25 Agile non-zero export shadow proof.

Alpha 7.24 proved zero-output outcome parity and corrected proposal/live solar
routing. Alpha 7.25 adds the proof required before real control work: when the
rolling Agile optimiser naturally selects a non-zero battery export with a
complete price horizon, apply that exact command to a one-step digital-twin
routing replay and require strict target/outcome parity.

The replay is deliberately command-shaped rather than a second optimiser. It
starts from Alpha 7.24's routed solar AC contribution, applies the requested
battery discharge through the configured battery, inverter and export limits,
and compares the resulting battery-to-home/export flow with the raw optimiser
command. Unsafe targets are not clipped into a pass: the existing independent
13-point validator remains authoritative and every proof check must pass.

This remains simulation/shadow only. It never calls a Home Assistant service,
never exposes a FoxESS write path, and never permits hardware commands.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from . import agile_alpha723_shadow as alpha723
from . import agile_alpha724_outcome as alpha724
from .kems_core import ControlConfig, ControlState, SimulationState

NONZERO_EXPORT_THRESHOLD_KW = 0.01
STRICT_TRACKING_TOLERANCE_KW = 0.01


def _number(value: Any) -> float | None:
    """Return one float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strict_tracking(
    target: dict[str, float],
    outcome: dict[str, float],
) -> dict[str, Any]:
    """Return strict one-step target/outcome tracking evidence."""
    difference = {
        key: round(float(outcome[key]) - float(target[key]), 3) for key in target
    }
    within = {
        key: abs(value) <= STRICT_TRACKING_TOLERANCE_KW + 1e-9
        for key, value in difference.items()
    }
    score = 100.0 * sum(bool(value) for value in within.values()) / max(len(within), 1)
    return {
        "basis": "candidate_applied_digital_twin",
        "tolerance_kw": STRICT_TRACKING_TOLERANCE_KW,
        "target": target,
        "outcome": outcome,
        "difference": difference,
        "within_tolerance": within,
        "tracking_score_percent": round(score, 1),
        "available": True,
    }


def _candidate_applied_replay(
    result: dict[str, Any],
    config: ControlConfig,
) -> dict[str, Any] | None:
    """Apply one safe Agile candidate to the Alpha7.24 routed AC snapshot.

    This is intentionally independent of the rolling optimiser. The target is
    copied from the candidate, while the outcome is recalculated from physical
    battery, inverter and export headroom. A command that exceeds a limit will
    therefore lose strict parity rather than being silently accepted.
    """
    candidate = result.get("candidate")
    routing = result.get("outcome_routing")
    if not isinstance(candidate, dict) or not isinstance(routing, dict):
        return None

    target_charge = max(_number(candidate.get("charge_kw")) or 0.0, 0.0)
    target_home = max(_number(candidate.get("battery_to_home_kw")) or 0.0, 0.0)
    target_export = max(_number(candidate.get("battery_export_kw")) or 0.0, 0.0)
    target_total = max(_number(candidate.get("total_discharge_kw")) or 0.0, 0.0)

    base_ac = max(_number(routing.get("total_kh7_ac_output_kw")) or 0.0, 0.0)
    base_discharge = max(
        _number(routing.get("base_digital_twin_discharge_kw")) or 0.0,
        0.0,
    )
    routed_solar_ac = max(base_ac - base_discharge, 0.0)
    inverter_headroom = max(config.inverter_limit_kw - routed_solar_ac, 0.0)

    if target_total > 0.0:
        replay_charge = 0.0
        available_discharge = min(config.max_discharge_kw, inverter_headroom)
        replay_home = min(target_home, available_discharge)
        remaining_discharge = max(available_discharge - replay_home, 0.0)
        replay_export = min(
            target_export,
            remaining_discharge,
            config.export_limit_kw,
        )
        replay_total = replay_home + replay_export
    else:
        replay_charge = min(target_charge, config.max_charge_kw)
        replay_home = 0.0
        replay_export = 0.0
        replay_total = 0.0

    target = {
        "charge_kw": round(target_charge, 3),
        "battery_to_home_kw": round(target_home, 3),
        "battery_export_kw": round(target_export, 3),
        "total_discharge_kw": round(target_total, 3),
    }
    outcome = {
        "charge_kw": round(replay_charge, 3),
        "battery_to_home_kw": round(replay_home, 3),
        "battery_export_kw": round(replay_export, 3),
        "total_discharge_kw": round(replay_total, 3),
    }
    tracking = _strict_tracking(target, outcome)
    replay_ac = routed_solar_ac + replay_total
    return {
        "basis": "candidate_applied_digital_twin",
        "routed_solar_ac_kw": round(routed_solar_ac, 3),
        "inverter_headroom_before_battery_kw": round(inverter_headroom, 3),
        "replayed_total_kh7_ac_output_kw": round(replay_ac, 3),
        "tracking": tracking,
    }


def evaluate_agile_nonzero_export_proof(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate Alpha7.24 and prove a genuine non-zero export when available."""
    result = alpha724.evaluate_agile_shadow_command_with_outcome_parity(
        control,
        simulation,
        config,
        agile_state,
    )
    candidate = result.get("candidate")
    if not isinstance(candidate, dict):
        result["nonzero_export_proof"] = {
            "state": "WAITING — Agile shadow candidate",
            "qualified": False,
            "passed": False,
            "hardware_writes": "blocked",
        }
        return result

    candidate_export = max(_number(candidate.get("battery_export_kw")) or 0.0, 0.0)
    optimizer = result.get("optimizer_target") or {}
    optimizer_export = max(_number(optimizer.get("battery_export_kw")) or 0.0, 0.0)
    horizon_complete = result.get("price_horizon_complete") is True
    horizon_held = bool(result.get("battery_export_held"))
    nonzero = candidate_export > NONZERO_EXPORT_THRESHOLD_KW
    qualified = bool(nonzero and horizon_complete and not horizon_held)

    if not qualified:
        if not nonzero:
            state = "WAITING — non-zero Agile export target"
            reason = "The optimiser has not selected battery export above 0.01 kW yet"
        elif not horizon_complete:
            state = "WAITING — complete Agile price horizon"
            reason = "A non-zero target is present, but the full price horizon is not complete"
        else:
            state = "WAITING — price-horizon export hold"
            reason = "A non-zero target is present while the export hold is still active"
        result["nonzero_export_proof"] = {
            "state": state,
            "reason": reason,
            "qualified": False,
            "passed": False,
            "candidate_export_kw": round(candidate_export, 3),
            "optimizer_export_kw": round(optimizer_export, 3),
            "price_horizon_complete": horizon_complete,
            "battery_export_held": horizon_held,
            "hardware_writes": "blocked",
        }
        return result

    replay = _candidate_applied_replay(result, config)
    tracking = (replay or {}).get("tracking") or {}
    within = tracking.get("within_tolerance") or {}
    safety = result.get("safety") or {}
    target_soc = _number(candidate.get("minimum_soc_percent"))
    candidate_total = max(_number(candidate.get("total_discharge_kw")) or 0.0, 0.0)
    candidate_ac = max(_number(candidate.get("total_kh7_ac_output_kw")) or 0.0, 0.0)

    checks = {
        "nonzero_optimizer_export": optimizer_export > NONZERO_EXPORT_THRESHOLD_KW,
        "export_target_matches_optimizer": abs(candidate_export - optimizer_export) <= 0.001,
        "command_parity": bool(result.get("parity_passed")),
        "complete_price_horizon": horizon_complete,
        "price_horizon_not_held": not horizon_held,
        "feed_in_first_mode": candidate.get("desired_work_mode") == "Feed-in First",
        "grid_export_allowed": bool(candidate.get("grid_export_allowed")),
        "independent_safety_13_of_13": bool(
            safety.get("passed")
            and safety.get("passed_checks") == 13
            and safety.get("total_checks") == 13
        ),
        "strict_outcome_parity": bool(within and all(bool(value) for value in within.values())),
        "strict_tracking_100_percent": tracking.get("tracking_score_percent") == 100.0,
        "discharge_within_limit": candidate_total <= config.max_discharge_kw + 1e-9,
        "kh7_ac_within_limit": candidate_ac <= config.inverter_limit_kw + 1e-9,
        "minimum_soc_respected": bool(
            target_soc is not None and target_soc + 1e-9 >= config.normal_reserve_percent
        ),
        "hardware_writes_blocked": bool(
            not result.get("safe_to_write_hardware")
            and not candidate.get("commands_permitted")
        ),
    }
    passed = bool(replay and all(checks.values()))
    proof = {
        "state": (
            "PASS — non-zero Agile export proof"
            if passed
            else "CHECK — non-zero Agile export proof"
        ),
        "qualified": True,
        "passed": passed,
        "strict_tolerance_kw": STRICT_TRACKING_TOLERANCE_KW,
        "candidate_export_kw": round(candidate_export, 3),
        "optimizer_export_kw": round(optimizer_export, 3),
        "price_horizon_complete": horizon_complete,
        "battery_export_held": horizon_held,
        "checks": checks,
        "replay": replay,
        "hardware_writes": "blocked",
    }

    # Alpha7.24 compares the candidate with the baseline digital twin, which is
    # correct for zero-output parity but intentionally does not execute a
    # separate Agile export request. For a qualified non-zero proof we retain
    # that baseline evidence and make the command-applied replay the active
    # outcome-parity evidence.
    result["baseline_tracking"] = result.get("tracking")
    result["baseline_outcome_parity"] = result.get("outcome_parity")
    result["tracking"] = tracking
    result["outcome_parity"] = {
        "passed": passed,
        "basis": tracking.get("basis"),
        "tracking_score_percent": tracking.get("tracking_score_percent"),
        "within_tolerance": tracking.get("within_tolerance"),
    }
    result["outcome_parity_passed"] = passed
    result["nonzero_export_proof"] = proof
    result["status"] = proof["state"]
    result["safe_to_write_hardware"] = False
    return result


def _record_agile_decision_with_nonzero_proof(self, result: dict[str, Any], now) -> None:
    """Persist compact Alpha7.25 proof evidence with the existing decisions."""
    alpha724._record_agile_decision_with_outcome(self, result, now)
    decisions = getattr(self, "_agile_decisions", None)
    if not isinstance(decisions, list) or not decisions:
        return
    latest = decisions[-1]
    if latest.get("timestamp") != now.isoformat():
        return
    proof = result.get("nonzero_export_proof") or {}
    replay = proof.get("replay") or {}
    strict_tracking = replay.get("tracking") or {}
    latest["nonzero_export_proof_state"] = proof.get("state")
    latest["nonzero_export_proof_passed"] = bool(proof.get("passed"))
    latest["strict_tracking_score_percent"] = strict_tracking.get(
        "tracking_score_percent"
    )
    latest["replay_battery_export_kw"] = (
        (strict_tracking.get("outcome") or {}).get("battery_export_kw")
    )
    self._dirty = True


_ALPHA725_DASHBOARD_CARDS = r"""      - type: entities
        title: Agile non-zero export proof
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_shadow_status
            name: Agile shadow status
          - entity: sensor.kems_agile_shadow_safety
            name: Independent safety
          - entity: sensor.kems_agile_shadow_command
            name: Desired inverter mode
          - entity: sensor.kems_agile_shadow_target_export
            name: Target battery export
          - entity: sensor.kems_agile_shadow_target_total_discharge
            name: Target total discharge
      - type: markdown
        title: Agile optimiser → command → non-zero replay
        content: |
          {% set s = states.sensor.kems_agile_shadow_status %}
          {% set c = states.sensor.kems_agile_shadow_command %}
          {% set safe = states.sensor.kems_agile_shadow_safety %}
          {% set proof = s.attributes.nonzero_export_proof if s else {} %}
          {% set replay = proof.replay if proof and proof.replay is defined else {} %}
          {% set strict = replay.tracking if replay and replay.tracking is defined else {} %}
          **Status:** **{{ s.state if s else 'Unavailable' }}**  
          **Non-zero proof:** **{{ proof.state if proof and proof.state is defined else 'Waiting' }}**  
          **Dispatch:** {{ s.attributes.dispatch_mode if s else '—' }}  
          **Price horizon complete:** {{ s.attributes.price_horizon_complete if s else '—' }}  
          **Target export:** {{ proof.candidate_export_kw if proof and proof.candidate_export_kw is defined else '—' }} kW  
          **Replay export:** {{ strict.outcome.battery_export_kw if strict and strict.outcome is defined else '—' }} kW  
          **Strict tracking:** {{ strict.tracking_score_percent if strict and strict.tracking_score_percent is defined else '—' }}%  
          **Strict tolerance:** {{ proof.strict_tolerance_kw if proof and proof.strict_tolerance_kw is defined else 0.01 }} kW  
          **Hardware writes:** **BLOCKED**

          | Command | KEMS target |
          |---|---:|
          | Work mode | {{ c.state if c else '—' }} |
          | Battery → home | {{ c.attributes.battery_to_home_kw if c else '—' }} kW |
          | Battery → export | {{ c.attributes.battery_export_kw if c else '—' }} kW |
          | Total discharge | {{ c.attributes.total_discharge_kw if c else '—' }} kW |
          | KH7 AC output | {{ c.attributes.total_kh7_ac_output_kw if c else '—' }} kW |
          | Minimum SOC | {{ c.attributes.minimum_soc_percent if c else '—' }}% |
          | Independent safety | {{ safe.state if safe else '—' }} |

          Alpha7.25 waits for a **genuine non-zero rolling Agile export target with a complete price horizon**. It then applies that exact command to the Alpha7.24 routed digital twin, rechecks battery/export/inverter limits, requires 13/13 independent safety and strict 0.01 kW target/outcome parity, and keeps FoxESS writes hard-blocked.
"""


def install_alpha725_nonzero_export_proof_patch() -> None:
    """Install non-zero Agile export proof after Alpha7.24."""
    if alpha723.evaluate_agile_shadow_command is not evaluate_agile_nonzero_export_proof:
        alpha723.evaluate_agile_shadow_command = evaluate_agile_nonzero_export_proof
    if alpha723._record_agile_decision is not _record_agile_decision_with_nonzero_proof:
        alpha723._record_agile_decision = _record_agile_decision_with_nonzero_proof
    alpha723._AGILE_DASHBOARD_CARDS = _ALPHA725_DASHBOARD_CARDS
