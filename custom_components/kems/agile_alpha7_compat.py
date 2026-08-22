"""Alpha7 Agile compatibility boundary for the Alpha8 consolidation baseline.

Alpha8 preserves proven Alpha7.52 behaviour while progressively moving historical
runtime monkey patches into canonical modules. New Alpha8 behaviour must be
implemented in canonical modules rather than by adding another version-named
patch module.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Final

PatchSpec = tuple[str, str]

# These patches historically had to be installed before runtime_base was imported.
PRE_BASE_PATCHES: Final[tuple[PatchSpec, ...]] = (
    ("agile_smart_export_reporting", "install_reporting_patch"),
    ("agile_deadline_dispatch", "install_deadline_patch"),
    ("agile_history_backfill_v2", "install_enhanced_backfill"),
    ("agile_alpha715_backfill", "install_alpha715_backfill_patch"),
)

# Preserve Alpha7.52 behaviour and installation semantics while replacing proven
# slices with canonical modules in small, parity-gated steps. Historical modules
# remain in the tree as regression evidence even after leaving this live registry.
POST_BASE_PATCHES: Final[tuple[PatchSpec, ...]] = (
    ("agile_rolling_replan", "install_rolling_replan_patch"),
    ("agile_smart_export_live", "install_live_scenario_patch"),
    ("agile_dashboard_yaml_guard", "install_dashboard_yaml_guard"),
    ("agile_alpha717_dispatch", "install_alpha717_dispatch_patch"),
    ("agile_alpha714_dashboard", "install_alpha714_dashboard_patch"),
    ("agile_alpha715_dashboard", "install_alpha715_dashboard_patch"),
    ("agile_alpha716_dashboard", "install_alpha716_dashboard_patch"),
    ("agile_alpha717_dashboard", "install_alpha717_dashboard_patch"),
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
    ("agile_price_publication", "install_price_publication"),
    ("agile_operator_telemetry", "install_operator_telemetry"),
    ("agile_event_priority", "install_event_priority"),
    ("agile_dashboard_parity", "install_dashboard_parity"),
    (
        "agile_progressive_publication",
        "install_progressive_publication_planning",
    ),
    ("agile_full_battery_routing", "install_full_battery_routing"),
    (
        "agile_deadline_plan_reconciliation",
        "install_deadline_plan_coverage",
    ),
    ("agile_publication_reporting", "install_no_reserve_reporting"),
    (
        "agile_deadline_plan_reconciliation",
        "install_maximum_discharge_plan_reconcile",
    ),
    ("agile_publication_reporting", "install_tomorrow_publication_reporting"),
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
