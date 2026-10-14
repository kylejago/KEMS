"""Physical energy binding for the frozen Agile deadline-guard runtime.

The old Alpha7 deadline implementation remains byte-identical for its frozen
regression contracts. A late, narrowly scoped wrapper supplies a verified
physical SOC to the live guard calculation, not to the digital-twin state.
If proof is absent, dispatch behaviour remains exactly as before.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .agile_deadline_guard import deadline_runtime
from .agile_physical_planning import physical_planning_soc
from .agile_rolling_planning import rolling_runtime as rolling
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_ORIGINAL_DEADLINE_CONTEXT = deadline_runtime._deadline_guard_context


def _physical_deadline_context(
    manager: Any,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Calculate urgency against verified physical energy, never alter replay."""
    soc, proof = physical_planning_soc(manager, now=now, config=config)
    if soc is None:
        return _ORIGINAL_DEADLINE_CONTEXT(
            manager, state, now=now, config=config, tariff=tariff
        )

    original_soc = rolling._current_agile_soc(state)
    physical_state = dict(state)
    # The frozen deadline context reads settled SOC first; only this private
    # ephemeral copy is substituted. The source state is never mutated.
    settled = dict(state.get("current_day_settlement_reconciliation") or {})
    settled["applied"] = True
    settled["ending_soc_percent"] = soc
    physical_state["current_day_settlement_reconciliation"] = settled
    context = _ORIGINAL_DEADLINE_CONTEXT(
        manager, physical_state, now=now, config=config, tariff=tariff
    )
    context["planning_soc_percent"] = round(soc, 3)
    context["planning_soc_source"] = "verified FoxESS physical lower bound"
    context["physical_planning_evidence"] = proof
    context["independent_simulated_soc_percent"] = original_soc
    # Diagnostic field remains the twin's value, not the ephemeral substitution.
    if original_soc is not None:
        context["simulated_soc_percent"] = round(original_soc, 2)
    return context


def install_physical_deadline_reconciliation() -> None:
    """Attach physical urgency without modifying frozen runtime source."""
    current = deadline_runtime._deadline_guard_context
    if getattr(current, "_kems_physical_deadline_reconciliation", False):
        return
    global _ORIGINAL_DEADLINE_CONTEXT
    _ORIGINAL_DEADLINE_CONTEXT = current
    _physical_deadline_context._kems_physical_deadline_reconciliation = True
    deadline_runtime._deadline_guard_context = _physical_deadline_context
