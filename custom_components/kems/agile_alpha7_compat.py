"""Alpha7 behaviour compatibility boundary for the Alpha8 consolidation baseline.

Alpha8 preserves proven Alpha7.52 behaviour through functional canonical owners.
Historical version-named modules remain packaged regression evidence, while the
live PRE_BASE_PATCHES and POST_BASE_PATCHES registries contain no version-named
Alpha7 runtime modules. New Alpha8 behaviour must be implemented in canonical
modules rather than by adding another version-named patch module.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Final

PatchSpec = tuple[str, str]

PRE_BASE_PATCHES: Final[tuple[PatchSpec, ...]] = (
    ("agile_smart_export_reporting", "install_reporting_patch"),
    ("agile_deadline_dispatch", "install_deadline_patch"),
    ("agile_history_backfill_enhancement", "install_history_backfill_enhancement"),
    ("agile_history_compatibility", "install_history_compatibility"),
)

POST_BASE_PATCHES: Final[tuple[PatchSpec, ...]] = (
    ("agile_rolling_planning", "install_rolling_replan"),
    ("agile_live_scenario", "install_live_scenario"),
    ("agile_live_scenario", "install_live_scenario_yaml_guard"),
    ("agile_settlement_dispatch", "install_settlement_dispatch"),
    ("agile_history_dashboard", "install_deadline_history_dashboard"),
    ("agile_history_dashboard", "install_history_diagnostics_dashboard"),
    ("agile_rolling_planning", "install_rolling_dashboard"),
    ("agile_settlement_dispatch", "install_settlement_dispatch_dashboard"),
    ("agile_validation_evidence", "install_validation_evidence"),
    ("dashboard_consolidation", "install_dashboard_consolidation"),
    ("agile_validation_evidence", "install_validation_dashboard"),
    ("agile_preinstall_evidence", "install_preinstall_evidence"),
    ("agile_preinstall_evidence", "install_preinstall_dashboard"),
    ("agile_price_horizon_safety", "install_price_horizon_safety"),
    ("agile_shadow_outcome", "install_shadow_command"),
    ("agile_shadow_outcome", "install_outcome_parity"),
    ("agile_proof_planning", "install_nonzero_export_proof"),
    ("agile_proof_planning", "install_provisional_planning"),
    ("agile_price_recovery", "install_price_recovery"),
    ("agile_bounded_partial", "install_bounded_partial_horizon"),
    ("agile_live_routing", "install_live_routing"),
    ("agile_routing", "install_current_routing"),
    ("agile_routing", "install_solar_headroom"),
    ("agile_deadline_guard", "install_deadline_guard"),
    ("agile_cheap_window_handover", "install_cheap_window_handover"),
    ("agile_product_presentation", "install_product_presentation"),
    ("agile_economic_opportunity", "install_economic_opportunity"),
    ("agile_forecast_arbitrage", "install_forecast_arbitrage"),
    ("agile_profit_first_headroom", "install_profit_first_headroom"),
    ("agile_price_publication", "install_price_publication"),
    ("agile_operator_telemetry", "install_operator_telemetry"),
    ("agile_event_priority", "install_event_priority"),
    ("happy_hour_auto", "install_automatic_happy_hour"),
    ("happy_hour_retention", "install_happy_hour_retention"),
    ("agile_dashboard_parity", "install_dashboard_parity"),
    ("agile_decision_evidence", "install_decision_evidence"),
    ("ev_policy_dashboard", "install_ev_policy_dashboard"),
    ("agile_progressive_publication", "install_progressive_publication_planning"),
    ("agile_full_battery_routing", "install_full_battery_routing"),
    ("agile_deadline_plan_reconciliation", "install_deadline_plan_coverage"),
    ("agile_publication_reporting", "install_no_reserve_reporting"),
    ("agile_deadline_plan_reconciliation", "install_maximum_discharge_plan_reconcile"),
    ("agile_publication_reporting", "install_tomorrow_publication_reporting"),
    ("agile_charge_recovery", "install_charge_recovery_policy"),
    (
        "agile_event_settlement_reconciliation",
        "install_event_settlement_reconciliation",
    ),
    ("agile_event_completion_migration", "install_event_completion_migration"),
    ("agile_dispatch_reconciliation", "install_dispatch_reconciliation"),
    ("agile_deadline_latch", "install_deadline_latch"),
    ("agile_runtime_reconciliation", "install_runtime_reconciliation"),
    ("agile_solar_net_demand", "install_solar_net_demand"),
    ("agile_total_discharge_ledger", "install_total_discharge_ledger"),
    ("agile_precheap_home_bridge", "install_precheap_home_bridge"),
    ("agile_current_slot_truth", "install_current_slot_truth"),
    ("agile_deadline_dominance", "install_deadline_dominance"),
)


def _install(spec: PatchSpec) -> None:
    """Import and install one compatibility or canonicalised behaviour slice."""
    module_name, installer_name = spec
    module = import_module(f".{module_name}", __package__)
    installer = getattr(module, installer_name)
    installer()


def install_alpha7_compatibility() -> ModuleType:
    """Install the Alpha7.52-equivalent runtime chain and return runtime_base."""
    for spec in PRE_BASE_PATCHES:
        _install(spec)

    base = import_module(".agile_smart_export_runtime_base", __package__)

    for spec in POST_BASE_PATCHES:
        _install(spec)

    return base
