"""Policy-aware publication guard for Agile future total-discharge parity.

The historical total-discharge parity owner is still responsible for restoring
missing future house/export presentation flow from the rolling ledger. Alpha9.24
adds the final planning-policy boundary around that owner so a legacy rolling
allocation cannot raise deliberate export above an already-capped canonical
future-flow projection.

This module is reporting-only. It never changes optimiser allocations, dispatch,
safety state, tariff decisions, or hardware-write authority.
"""

from __future__ import annotations

from typing import Any

from .agile_flow_total_discharge_parity import _reconcile_future_total_discharge_flow


def _reconcile_future_policy_safe_total_discharge_flow(state: dict[str, Any]) -> int:
    """Run the established future parity owner behind the Alpha9 policy boundary."""
    return _reconcile_future_total_discharge_flow(state)
