"""Alpha 7.26 provisional Agile planning and BST horizon diagnostics.

Alpha7.22 correctly blocks deliberate battery export while a relevant Agile price
is unknown, but it also erases the economic plan. Alpha7.26 separates those two
concerns: the dispatch-safe plan remains held at zero, while a provisional
economic allocation is retained for transparency and SOC planning.

The price fetch also performs a small targeted retry for still-missing future
local-day slots after the normal broad fetch. This is intentionally diagnostic
and conservative: unresolved prices remain explicit and continue to block live
price-optimised export.

This remains simulation/shadow only. It never permits FoxESS hardware writes.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from aiohttp import ClientError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import agile_alpha719_dashboard as alpha719_dashboard
from . import agile_alpha719_validation as alpha719_validation
from . import agile_alpha722_horizon as alpha722
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_price_horizon import expected_slots_for_day, missing_slots_for_day
from .kems_core import SimulationConfig
from .tariff import TariffSettings

MAX_TARGETED_RATE_RETRIES = 4
_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return a float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_utc(value: Any) -> datetime | None:
    """Parse an ISO timestamp and normalise it to UTC."""
    if value in (None, ""):
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _future_missing_capacity_kwh(
    missing_slots: list[dict[str, Any]],
    *,
    now: datetime,
    deadline: datetime | None,
    max_kw: float,
) -> float:
    """Return maximum discharge energy available in unresolved future slots."""
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC) if deadline is not None else None
    capacity = 0.0
    for item in missing_slots:
        start = _parse_utc(item.get("valid_from"))
        end = _parse_utc(item.get("valid_to"))
        if start is None or end is None:
            continue
        overlap_start = max(start, now_utc)
        overlap_end = end if deadline_utc is None else min(end, deadline_utc)
        if overlap_end <= overlap_start:
            continue
        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        capacity += max(max_kw, 0.0) * hours
    return max(capacity, 0.0)


def _reserve_unknown_capacity(
    selected: list[dict[str, Any]],
    reserve_kwh: float,
) -> tuple[list[dict[str, Any]], float]:
    """Trim lowest-priced known allocations to reserve unresolved-slot capacity."""
    rows = [dict(item) for item in selected if isinstance(item, dict)]
    remaining = min(
        max(reserve_kwh, 0.0),
        sum(
            max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
            for item in rows
        ),
    )
    reserved = remaining
    for item in sorted(
        rows,
        key=lambda value: (
            _number(value.get("rate_pence")) or 0.0,
            str(value.get("valid_from") or ""),
        ),
    ):
        if remaining <= _EPSILON:
            break
        allocation = max(
            _number(item.get("planned_battery_export_kwh")) or 0.0,
            0.0,
        )
        reduction = min(allocation, remaining)
        item["planned_battery_export_kwh"] = round(allocation - reduction, 3)
        remaining -= reduction
    rows = [
        item
        for item in rows
        if (_number(item.get("planned_battery_export_kwh")) or 0.0) > _EPSILON
    ]
    rows.sort(key=lambda value: str(value.get("valid_from") or ""))
    return rows, round(max(reserved - remaining, 0.0), 3)


def _deadline_from_horizon(horizon: dict[str, Any]) -> datetime | None:
    """Return the horizon deadline when available."""
    return _parse_utc(horizon.get("deadline"))


def _provisional_hold_price_optimised_export(
    state: dict[str, Any],
    plan: dict[str, Any],
    horizon: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Keep the economic plan visible while Alpha7.22 blocks live dispatch."""
    selected_before = [
        dict(item) for item in plan.get("selected_slots", []) if isinstance(item, dict)
    ]
    slot_before: dict[str, dict[str, Any]] = {}
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        key = str(slot.get("valid_from") or "")
        slot_before[key] = {
            "target_kw": _number(slot.get("rolling_target_battery_export_kw")) or 0.0,
            "action": slot.get("rolling_action"),
        }

    alpha722_original_hold(state, plan, horizon, now=now)

    if not horizon.get("battery_export_held"):
        plan["provisional_plan_active"] = False
        plan["dispatch_blocked_for_price_horizon"] = False
        return

    missing = [
        dict(item)
        for item in horizon.get("missing_slots", [])
        if isinstance(item, dict)
    ]
    deadline = _deadline_from_horizon(horizon)
    max_kw = _number(plan.get("effective_discharge_kw")) or 0.0
    reserve_capacity = _future_missing_capacity_kwh(
        missing,
        now=now,
        deadline=deadline,
        max_kw=max_kw,
    )
    provisional_selected, reserved = _reserve_unknown_capacity(
        selected_before,
        reserve_capacity,
    )
    selected_by_start = {
        str(item.get("valid_from") or ""): item for item in provisional_selected
    }
    provisional_planned = round(
        sum(
            max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
            for item in provisional_selected
        ),
        3,
    )
    original_planned = round(
        sum(
            max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
            for item in selected_before
        ),
        3,
    )

    plan["provisional_plan_active"] = True
    plan["economic_plan_status"] = "provisional_price_horizon"
    plan["dispatch_blocked_for_price_horizon"] = True
    plan["dispatch_permitted_battery_export_kw"] = 0.0
    plan["provisional_selected_slots"] = provisional_selected
    plan["provisional_planned_battery_export_kwh"] = provisional_planned
    plan["provisional_full_known_price_plan_kwh"] = original_planned
    plan["provisional_reserved_unknown_capacity_kwh"] = reserved
    plan["provisional_unresolved_price_slots"] = [
        str(item.get("label") or item.get("local_from") or "unknown")
        for item in missing
    ]
    plan["provisional_next_export_slot"] = (
        provisional_selected[0] if provisional_selected else None
    )

    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        key = str(slot.get("valid_from") or "")
        before = slot_before.get(key, {})
        provisional = selected_by_start.get(key)
        planned_kwh = (
            max(
                _number(provisional.get("planned_battery_export_kwh")) or 0.0,
                0.0,
            )
            if provisional is not None
            else 0.0
        )
        slot["provisional_planned_battery_export_kwh"] = round(planned_kwh, 3)
        slot["provisional_target_battery_export_kw"] = round(
            (
                max(_number(before.get("target_kw")) or 0.0, 0.0)
                if planned_kwh > _EPSILON
                else 0.0
            ),
            3,
        )
        if planned_kwh > _EPSILON:
            slot["provisional_action"] = (
                before.get("action") or "planned battery export — provisional"
            )
        else:
            slot["provisional_action"] = "hold — provisional economic plan"
        slot["dispatch_action"] = plan.get("dispatch_action")


async def _fetch_rates_with_targeted_retry(self, records, now: datetime) -> None:
    """Retry unresolved future local-day rates without weakening horizon safety."""
    await alpha726_original_fetch_rates(self, records, now)

    local_day = now.astimezone(agile.LONDON).date()
    expected = expected_slots_for_day(local_day, agile.LONDON)
    slots = [
        {
            "valid_from": item.valid_from.isoformat(),
            "valid_to": item.valid_to.isoformat(),
        }
        for item in self._rates
    ]
    missing_before = missing_slots_for_day(slots, local_day, agile.LONDON)
    now_utc = now.astimezone(UTC)
    future_missing = [
        item
        for item in missing_before
        if (_parse_utc(item.get("valid_to")) or now_utc) > now_utc
    ][:MAX_TARGETED_RATE_RETRIES]

    diagnostics: dict[str, Any] = {
        "local_date": local_day.isoformat(),
        "expected_slots": len(expected),
        "known_after_primary_fetch": len(expected) - len(missing_before),
        "primary_missing_labels": [
            str(item.get("label") or "unknown") for item in missing_before
        ],
        "targeted_retry_attempted": bool(future_missing),
        "targeted_retry_slots": [
            str(item.get("label") or "unknown") for item in future_missing
        ],
        "targeted_retry_recovered": [],
        "targeted_retry_error": None,
    }

    recovered_rates: list[agile.AgileRate] = []
    if future_missing and self._rate_url and self._product_code and self._tariff_code:
        session = async_get_clientsession(self._hass)
        try:
            for slot in future_missing:
                start = _parse_utc(slot.get("valid_from"))
                end = _parse_utc(slot.get("valid_to"))
                if start is None or end is None:
                    continue
                params = {
                    "period_from": agile._api_dt(start),
                    "period_to": agile._api_dt(end),
                    "page_size": 10,
                }
                async with session.get(
                    self._rate_url,
                    params=params,
                    timeout=15,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                for item in data.get("results", []):
                    if not isinstance(item, dict) or item.get("valid_to") is None:
                        continue
                    recovered_rates.append(
                        agile.AgileRate.from_dict(
                            {
                                "product_code": self._product_code,
                                "tariff_code": self._tariff_code,
                                "value_inc_vat": item["value_inc_vat"],
                                "valid_from": item["valid_from"],
                                "valid_to": item["valid_to"],
                            }
                        )
                    )
        except (ClientError, TimeoutError, KeyError, TypeError, ValueError) as err:
            diagnostics["targeted_retry_error"] = str(err)

    if recovered_rates:
        self._rates = agile._dedupe([*self._rates, *recovered_rates])
        self._dirty = True

    slots_after = [
        {
            "valid_from": item.valid_from.isoformat(),
            "valid_to": item.valid_to.isoformat(),
        }
        for item in self._rates
    ]
    missing_after = missing_slots_for_day(slots_after, local_day, agile.LONDON)
    missing_after_labels = {
        str(item.get("label") or "unknown") for item in missing_after
    }
    diagnostics["targeted_retry_recovered"] = [
        str(item.get("label") or "unknown")
        for item in future_missing
        if str(item.get("label") or "unknown") not in missing_after_labels
    ]
    diagnostics["known_after_targeted_retry"] = len(expected) - len(missing_after)
    diagnostics["unresolved_missing_labels"] = [
        str(item.get("label") or "unknown") for item in missing_after
    ]
    self._kems_alpha726_rate_fetch_diagnostics = diagnostics


def _decision_audit_with_provisional(
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Expose economic intent separately from zeroed dispatch-safe targets."""
    result = alpha726_original_decision_audit(state, now)
    slots = {
        str(item.get("valid_from") or ""): item
        for item in state.get("today_slots", [])
        if isinstance(item, dict)
    }
    for row in result.get("today", []):
        if not isinstance(row, dict):
            continue
        slot = slots.get(str(row.get("valid_from") or ""), {})
        row["dispatch_battery_export_kwh"] = row.get("planned_battery_export_kwh")
        row["provisional_planned_battery_export_kwh"] = slot.get(
            "provisional_planned_battery_export_kwh"
        )
        row["provisional_action"] = slot.get("provisional_action")
        row["dispatch_action"] = slot.get("dispatch_action") or slot.get(
            "rolling_action"
        )

    now_utc = now.astimezone(UTC)
    result["upcoming"] = [
        row
        for row in result.get("today", [])
        if isinstance(row, dict)
        and (_parse_utc(row.get("valid_to")) or now_utc) > now_utc
    ][:24]
    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    result["economic_plan_status"] = plan.get("economic_plan_status")
    result["dispatch_blocked_for_price_horizon"] = bool(
        plan.get("dispatch_blocked_for_price_horizon")
    )
    result["provisional_planned_battery_export_kwh"] = plan.get(
        "provisional_planned_battery_export_kwh"
    )
    result["provisional_reserved_unknown_capacity_kwh"] = plan.get(
        "provisional_reserved_unknown_capacity_kwh"
    )
    result["unresolved_price_slots"] = plan.get(
        "provisional_unresolved_price_slots",
        [],
    )
    return result


def _soc_trajectory_with_provisional(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
    forecast_plan,
) -> dict[str, Any]:
    """Publish both safety-hold and provisional economic SOC outcomes."""
    hold = alpha726_original_soc_trajectory(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
        forecast_plan=forecast_plan,
    )
    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    if not hold.get("available") or not plan.get("provisional_plan_active"):
        return hold

    provisional_state = copy.deepcopy(state)
    for slot in provisional_state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        if "provisional_planned_battery_export_kwh" in slot:
            slot["rolling_planned_battery_export_kwh"] = slot.get(
                "provisional_planned_battery_export_kwh"
            )
            slot["rolling_action"] = slot.get("provisional_action")
    provisional = alpha726_original_soc_trajectory(
        self,
        provisional_state,
        now=now,
        config=config,
        tariff=tariff,
        forecast_plan=forecast_plan,
    )

    hold_deadline = _number(hold.get("projected_deadline_soc_percent"))
    known_plan_deadline = _number(provisional.get("projected_deadline_soc_percent"))
    reserve_ac = max(
        _number(plan.get("provisional_reserved_unknown_capacity_kwh")) or 0.0,
        0.0,
    )
    planned_deadline = known_plan_deadline
    if known_plan_deadline is not None and reserve_ac > _EPSILON:
        reserve_stored = reserve_ac / max(config.discharge_efficiency, 0.01)
        reserve_soc = 100.0 * reserve_stored / max(config.battery_capacity_kwh, 0.1)
        planned_deadline = max(
            _number(hold.get("target_soc_percent")) or config.battery_reserve_percent,
            known_plan_deadline - reserve_soc,
        )

    hold["basis"] = "receding_horizon_conservative_with_provisional_plan"
    hold["hold_projected_deadline_soc_percent"] = hold_deadline
    hold["provisional_known_price_deadline_soc_percent"] = (
        round(known_plan_deadline, 1) if known_plan_deadline is not None else None
    )
    hold["provisional_projected_deadline_soc_percent"] = (
        round(planned_deadline, 1) if planned_deadline is not None else None
    )
    hold["provisional_reserved_unknown_capacity_kwh"] = round(reserve_ac, 3)
    hold["unresolved_price_slots"] = plan.get(
        "provisional_unresolved_price_slots",
        [],
    )
    hold["economic_plan_status"] = plan.get("economic_plan_status")
    hold["dispatch_status"] = "blocked_price_horizon"
    hold["provisional_points"] = provisional.get("points", [])
    hold["note"] = (
        "Safety-hold SOC remains the executable projection while the Agile horizon "
        "is incomplete. A separate provisional economic trajectory preserves the "
        "known-price allocation and reserves capacity for unresolved future slots."
    )
    return hold


def _publish_with_alpha726(self, state: dict[str, Any]) -> None:
    """Publish provisional-plan and rate-fetch diagnostics after existing cards."""
    alpha726_original_publish(self, state)

    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    provisional = [
        dict(item)
        for item in plan.get("provisional_selected_slots", [])
        if isinstance(item, dict)
    ]
    planned = _number(plan.get("provisional_planned_battery_export_kwh")) or 0.0
    reserve = _number(plan.get("provisional_reserved_unknown_capacity_kwh")) or 0.0
    if plan.get("provisional_plan_active"):
        state_text = f"{len(provisional)} slots · {planned:.2f} kWh provisional"
    else:
        state_text = "Not required"

    self._set(
        "sensor.kems_agile_provisional_export_plan",
        state_text,
        {
            "friendly_name": "Agile provisional economic export plan",
            "mode": "simulation_only",
            "economic_plan_status": plan.get("economic_plan_status"),
            "dispatch_blocked_for_price_horizon": bool(
                plan.get("dispatch_blocked_for_price_horizon")
            ),
            "dispatch_permitted_battery_export_kw": plan.get(
                "dispatch_permitted_battery_export_kw"
            ),
            "planned_battery_export_kwh": round(planned, 3),
            "reserved_unknown_capacity_kwh": round(reserve, 3),
            "unresolved_price_slots": plan.get(
                "provisional_unresolved_price_slots",
                [],
            ),
            "selected_slots": provisional,
            "hardware_writes": "blocked",
        },
    )

    diagnostics = getattr(self, "_kems_alpha726_rate_fetch_diagnostics", {})
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    unresolved = diagnostics.get("unresolved_missing_labels") or []
    self._set(
        "sensor.kems_agile_price_fetch_diagnostics",
        (
            f"{diagnostics.get('known_after_targeted_retry', '—')}/"
            f"{diagnostics.get('expected_slots', '—')} slots"
            if diagnostics
            else "Unavailable"
        ),
        {
            "friendly_name": "Agile price fetch diagnostics",
            "mode": "simulation_only",
            **diagnostics,
            "unresolved_count": len(unresolved),
        },
    )


_ALPHA726_AGILE_CARDS = r"""      - type: entities
        title: Agile validation evidence
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_comparison_evidence
            name: Fixed-window evidence
          - entity: sensor.kems_agile_decision_audit
            name: Current decision reason
          - entity: sensor.kems_agile_provisional_export_plan
            name: Provisional economic export plan
          - entity: sensor.kems_agile_price_horizon_status
            name: Dispatch price horizon
          - entity: sensor.kems_agile_price_fetch_diagnostics
            name: Price fetch diagnostics
          - entity: sensor.kems_agile_soc_trajectory
            name: Current simulated SOC
          - entity: sensor.kems_agile_projected_soc_at_deadline
            name: Executable projected SOC
          - entity: sensor.kems_agile_overnight_recharge_target
            name: Overnight recharge target
      - type: markdown
        title: Receding-horizon SOC trajectory
        content: |
          {% set t = states.sensor.kems_agile_soc_trajectory %}
          {% set p = states.sensor.kems_agile_provisional_export_plan %}
          **Basis:** {{ t.attributes.basis if t else '—' }}  
          **Current SOC:** {{ t.attributes.current_soc_percent if t else '—' }}%  
          **23:30 target:** {{ t.attributes.target_soc_percent if t else '—' }}%  
          **If safety hold continues:** {{ t.attributes.hold_projected_deadline_soc_percent if t and t.attributes.hold_projected_deadline_soc_percent is defined else t.attributes.projected_deadline_soc_percent if t else '—' }}%  
          **With provisional economic plan:** {{ t.attributes.provisional_projected_deadline_soc_percent if t and t.attributes.provisional_projected_deadline_soc_percent is defined else '—' }}%  
          **Reserved for unresolved price slots:** {{ t.attributes.provisional_reserved_unknown_capacity_kwh if t and t.attributes.provisional_reserved_unknown_capacity_kwh is defined else 0 }} kWh  
          **Unresolved prices:** {{ (t.attributes.unresolved_price_slots if t and t.attributes.unresolved_price_slots is defined else []) | join(', ') or 'None' }}  
          **Dispatch permission:** **{{ 'BLOCKED — price horizon incomplete' if p and p.attributes.dispatch_blocked_for_price_horizon else 'Available to normal safety chain' }}**  
          **Overnight target:** {{ t.attributes.overnight_target_soc_percent if t else '—' }}%  
          **Projected morning SOC:** {{ t.attributes.projected_morning_soc_percent if t else '—' }}%

          The executable projection remains conservative while prices are missing. The provisional projection shows where KEMS economically intends to export using known rates, while reserving discharge capacity for unresolved future slots. Future solar is still **not pre-spent**.
      - type: markdown
        title: Upcoming Agile economic plan vs dispatch
        content: |
          {% set a = states.sensor.kems_agile_decision_audit %}
          **Economic plan:** {{ a.attributes.economic_plan_status if a and a.attributes.economic_plan_status else 'normal' }}  
          **Dispatch held:** {{ a.attributes.dispatch_blocked_for_price_horizon if a else '—' }}  
          **Provisional export planned:** {{ a.attributes.provisional_planned_battery_export_kwh if a and a.attributes.provisional_planned_battery_export_kwh is not none else 0 }} kWh  
          **Reserved unknown-slot capacity:** {{ a.attributes.provisional_reserved_unknown_capacity_kwh if a and a.attributes.provisional_reserved_unknown_capacity_kwh is not none else 0 }} kWh  
          **Unresolved prices:** {{ (a.attributes.unresolved_price_slots if a else []) | join(', ') or 'None' }}

          | Time | Rate | Economic plan | Provisional export | Dispatch |
          |---|---:|---|---:|---|
          {% for item in (a.attributes.upcoming if a else []) %}
          | {{ item.get('label', '—') }} | {{ item.get('rate_pence', '—') }}p | {{ item.get('provisional_action') or 'hold' }} | {{ item.get('provisional_planned_battery_export_kwh') if item.get('provisional_planned_battery_export_kwh') is not none else 0 }} kWh | {{ item.get('dispatch_action') or item.get('rolling_action') or '—' }} |
          {% endfor %}
"""


def install_alpha726_provisional_planning_patch() -> None:
    """Install provisional planning, targeted price retry, and dual SOC evidence."""
    global alpha722_original_hold
    global alpha726_original_decision_audit
    global alpha726_original_fetch_rates
    global alpha726_original_publish
    global alpha726_original_soc_trajectory

    current_hold = alpha722._hold_price_optimised_export
    if not getattr(current_hold, "_kems_alpha726_provisional", False):
        alpha722_original_hold = current_hold
        _provisional_hold_price_optimised_export._kems_alpha726_provisional = True
        alpha722._hold_price_optimised_export = _provisional_hold_price_optimised_export

    current_fetch = runtime.EfficientAgileSmartExportManager._fetch_rates
    if not getattr(current_fetch, "_kems_alpha726_targeted_retry", False):
        alpha726_original_fetch_rates = current_fetch
        _fetch_rates_with_targeted_retry._kems_alpha726_targeted_retry = True
        runtime.EfficientAgileSmartExportManager._fetch_rates = (
            _fetch_rates_with_targeted_retry
        )

    current_audit = alpha719_validation._decision_audit
    if not getattr(current_audit, "_kems_alpha726_provisional", False):
        alpha726_original_decision_audit = current_audit
        _decision_audit_with_provisional._kems_alpha726_provisional = True
        alpha719_validation._decision_audit = _decision_audit_with_provisional

    current_trajectory = alpha719_validation._soc_trajectory
    if not getattr(current_trajectory, "_kems_alpha726_provisional", False):
        alpha726_original_soc_trajectory = current_trajectory
        _soc_trajectory_with_provisional._kems_alpha726_provisional = True
        alpha719_validation._soc_trajectory = _soc_trajectory_with_provisional

    current_publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(current_publish, "_kems_alpha726_provisional", False):
        alpha726_original_publish = current_publish
        _publish_with_alpha726._kems_alpha726_provisional = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_alpha726

    alpha719_dashboard._AGILE_CARDS = _ALPHA726_AGILE_CARDS
