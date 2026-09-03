"""Hard-latch the Agile 10% deadline once latest-safe-start is reached.

Alpha8.20 closes a rolling-replan loophole where economic plan coverage could
suppress an already-active deadline guard, allow the optimiser to wait again,
and later fall into ``maximum_discharge`` after the 10% target had become
physically unreachable.

Alpha8.73 binds that durable latch to its own immutable guarded-deadline
identity. An identityless latch may not persist, and a later guard may not lend
its newer deadline to an older latch. This prevents prior-day emergency state
from sliding onto the next planning horizon while preserving same-deadline
anti-oscillation protection.

Once a guarded deadline has activated, price optimisation may not reassert
control until the target is reached or the guarded cheap-window deadline begins.
Power Down / Happy Hour / other explicit higher-priority modes are not replaced.
This remains simulation/shadow only; real hardware writes stay blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_deadline_plan_reconciliation as reconciliation
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_SOC_TOLERANCE_PERCENT = 0.05
_LATCH_ATTR = "_kems_deadline_discharge_latch"
_DEADLINE_MODES = frozenset({"deadline_following", "maximum_discharge"})
_PRICE_MODES = frozenset({"price_optimised", "deadline_following"})


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _datetime(value: Any) -> datetime | None:
    """Parse one timestamp as UTC."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return None


def _guard(targets: dict[str, Any]) -> dict[str, Any]:
    value = targets.get("deadline_guard")
    return dict(value) if isinstance(value, dict) else {}


def _soc_and_target(guard: dict[str, Any]) -> tuple[float | None, float | None]:
    soc = _number(guard.get("simulated_soc_percent"))
    if soc is None:
        soc = _number(guard.get("soc_percent"))
    target = _number(guard.get("target_soc_percent"))
    return soc, target


def _deadline_from(latch: dict[str, Any], guard: dict[str, Any]) -> datetime | None:
    """Return only the immutable deadline owned by the active latch.

    ``guard`` is intentionally ignored. Before Alpha8.73 an identityless old
    latch borrowed the currently recalculated guard deadline, allowing the old
    activation to slide into a new planning day.
    """
    del guard
    return _datetime(latch.get("deadline"))


def _release_reason(
    latch: dict[str, Any], guard: dict[str, Any], *, now: datetime
) -> str | None:
    """Return why an active latch may be released, otherwise ``None``."""
    soc, target = _soc_and_target(guard)
    if (
        soc is not None
        and target is not None
        and soc <= target + _SOC_TOLERANCE_PERCENT
    ):
        return "target_reached"

    deadline = _deadline_from(latch, guard)
    if deadline is None:
        return "deadline_identity_missing"
    if now.astimezone(UTC) >= deadline:
        return "cheap_window_started"

    current_deadline = _datetime(guard.get("deadline"))
    if current_deadline is not None and current_deadline != deadline:
        return "deadline_identity_advanced"
    return None


def _suppressed_active_guard(targets: dict[str, Any], guard: dict[str, Any]) -> bool:
    """Detect the exact Alpha8.19 loop: active guard suppressed by price coverage."""
    if not targets.get("deadline_guard_suppressed_by_plan_coverage"):
        return False
    return str(guard.get("raw_mode") or "") == "deadline_following"


def _new_latch(guard: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Create durable per-manager latch evidence bound to one deadline."""
    _, target = _soc_and_target(guard)
    deadline = _datetime(guard.get("deadline"))
    if deadline is None:
        return {}
    return {
        "active": True,
        "activated_at": now.astimezone(UTC).isoformat(),
        "deadline": deadline.isoformat(),
        "target_soc_percent": target,
        "reason": "guarded latest-safe-start reached",
    }


def _safe_deadline_power(
    targets: dict[str, Any], guard: dict[str, Any], config: SimulationConfig
) -> tuple[float, float, float]:
    """Rebuild the same full-safe battery path used by the deadline guard."""
    evidence = targets.get("solar_aware_inverter_headroom")
    evidence = dict(evidence) if isinstance(evidence, dict) else {}
    safe_battery_kw = _number(evidence.get("battery_inverter_headroom_kw"))
    if safe_battery_kw is None:
        safe_battery_kw = _number(guard.get("current_battery_headroom_kw"))
    if safe_battery_kw is None:
        safe_battery_kw = max(config.max_discharge_kw, 0.0)
    safe_battery_kw = min(
        max(safe_battery_kw, 0.0),
        max(config.max_discharge_kw, 0.0),
        max(config.inverter_limit_kw, 0.0),
    )

    house_kw = min(
        max(_number(targets.get("house_battery_kw")) or 0.0, 0.0),
        safe_battery_kw,
    )
    export_kw = min(
        max(safe_battery_kw - house_kw, 0.0),
        max(config.export_limit_kw, 0.0),
        max(config.inverter_limit_kw - house_kw, 0.0),
        max(config.max_discharge_kw - house_kw, 0.0),
    )
    return house_kw, export_kw, house_kw + export_kw


def _apply_latch(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    targets: dict[str, Any],
    latch: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Make the guarded deadline authoritative over later price replans."""
    guard = _guard(targets)
    house_kw, export_kw, total_kw = _safe_deadline_power(targets, guard, config)
    targets.update(
        {
            "mode": "deadline_following",
            "action": (
                "deadline latch active — continue full safe discharge until "
                "10% target"
            ),
            "house_battery_kw": round(house_kw, 3),
            "battery_export_target_kw": round(export_kw, 3),
            "battery_discharge_target_kw": round(total_kw, 3),
            "deadline_guard_suppressed_by_plan_coverage": False,
            "deadline_latch_active": True,
            "deadline_latch_activated_at": latch.get("activated_at"),
            "deadline_latch_deadline": latch.get("deadline"),
        }
    )
    guard.update(
        {
            "mode": "deadline_following",
            "deadline_guard_active": True,
            "suppressed_by_economic_plan_coverage": False,
            "deadline_latch_active": True,
            "deadline_latch_activated_at": latch.get("activated_at"),
            "deadline_latch_deadline": latch.get("deadline"),
            "deadline_latch_reason": latch.get("reason"),
        }
    )
    plan["deadline_guard_suppressed_by_plan_coverage"] = False
    plan["deadline_latch_active"] = True
    plan["deadline_latch_activated_at"] = latch.get("activated_at")
    plan["deadline_latch_deadline"] = latch.get("deadline")

    evidence = targets.get("solar_aware_inverter_headroom")
    if isinstance(evidence, dict):
        evidence = dict(evidence)
        evidence["deadline_guard_applied"] = True
        evidence["economic_plan_coverage_override"] = False
        evidence["deadline_latch_active"] = True
        evidence["permitted_battery_to_home_kw"] = round(house_kw, 3)
        evidence["permitted_battery_export_kw"] = round(export_kw, 3)
        evidence["permitted_total_discharge_kw"] = round(total_kw, 3)
        targets["solar_aware_inverter_headroom"] = evidence

    rebalance = reconciliation._rebalance_deadline_forced_current_slot(
        state,
        plan,
        now=now,
        export_target_kw=export_kw,
    )
    plan["deadline_plan_rebalance"] = rebalance
    targets["deadline_plan_rebalance"] = rebalance
    guard["deadline_plan_rebalance"] = rebalance
    targets["deadline_guard"] = guard
    self._kems_alpha734_deadline_guard = dict(guard)
    return targets


def _dispatch_with_deadline_latch(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff,
) -> dict[str, Any]:
    """Keep deadline discharge latched across rolling economic replans."""
    targets = _original_deadline_latch_dispatch(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(targets, dict):
        return targets

    guard = _guard(targets)
    latch = getattr(self, _LATCH_ATTR, None)
    latch = dict(latch) if isinstance(latch, dict) and latch.get("active") else {}

    if latch:
        release = _release_reason(latch, guard, now=now)
        if release is not None:
            setattr(self, _LATCH_ATTR, None)
            targets["deadline_latch_active"] = False
            targets["deadline_latch_released"] = release
            targets["deadline_latch_released_deadline"] = latch.get("deadline")
            guard["deadline_latch_active"] = False
            guard["deadline_latch_released"] = release
            guard["deadline_latch_released_deadline"] = latch.get("deadline")
            targets["deadline_guard"] = guard
            return targets

    mode = str(targets.get("mode") or "")
    suppression_attempt = _suppressed_active_guard(targets, guard)
    if not latch and (mode in _DEADLINE_MODES or suppression_attempt):
        latch = _new_latch(guard, now=now)
        if latch:
            setattr(self, _LATCH_ATTR, dict(latch))
        else:
            targets["deadline_latch_active"] = False
            targets["deadline_latch_not_armed"] = "deadline_identity_missing"
            guard["deadline_latch_active"] = False
            guard["deadline_latch_not_armed"] = "deadline_identity_missing"
            targets["deadline_guard"] = guard

    if not latch:
        return targets

    # Preserve genuinely higher-priority modes. The latch remains armed and
    # resumes when that explicit event finishes, unless the target/deadline has
    # already released it.
    if mode not in _PRICE_MODES and mode != "maximum_discharge":
        targets["deadline_latch_active"] = True
        targets["deadline_latch_activated_at"] = latch.get("activated_at")
        targets["deadline_latch_deadline"] = latch.get("deadline")
        targets["deadline_latch_deferred_by_mode"] = mode
        return targets

    if mode == "maximum_discharge":
        targets["deadline_latch_active"] = True
        targets["deadline_latch_activated_at"] = latch.get("activated_at")
        targets["deadline_latch_deadline"] = latch.get("deadline")
        guard["deadline_latch_active"] = True
        guard["deadline_latch_activated_at"] = latch.get("activated_at")
        guard["deadline_latch_deadline"] = latch.get("deadline")
        targets["deadline_guard"] = guard
        return targets

    return _apply_latch(
        self,
        state,
        plan,
        targets,
        latch,
        now=now,
        config=config,
    )


def install_deadline_latch() -> None:
    """Install the final hard deadline latch after all rolling reconciliation."""
    dispatch = alpha717._dispatch_targets
    if getattr(dispatch, "_kems_deadline_latch", False):
        return

    global _original_deadline_latch_dispatch
    _original_deadline_latch_dispatch = dispatch
    _dispatch_with_deadline_latch._kems_deadline_latch = True
    alpha717._dispatch_targets = _dispatch_with_deadline_latch
