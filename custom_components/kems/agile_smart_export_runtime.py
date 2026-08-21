"""Efficient Agile runtime loader with reporting, deadline, and history fixes."""

from __future__ import annotations

from .agile_smart_export_reporting import install_reporting_patch

install_reporting_patch()

from .agile_alpha715_backfill import install_alpha715_backfill_patch  # noqa: E402
from .agile_deadline_dispatch import install_deadline_patch  # noqa: E402
from .agile_history_backfill_v2 import install_enhanced_backfill  # noqa: E402

install_deadline_patch()
install_enhanced_backfill()
install_alpha715_backfill_patch()

from . import agile_smart_export_runtime_base as _base  # noqa: E402
from .agile_alpha714_dashboard import install_alpha714_dashboard_patch  # noqa: E402
from .agile_alpha715_dashboard import install_alpha715_dashboard_patch  # noqa: E402
from .agile_alpha716_dashboard import install_alpha716_dashboard_patch  # noqa: E402
from .agile_alpha717_dashboard import install_alpha717_dashboard_patch  # noqa: E402
from .agile_alpha717_dispatch import install_alpha717_dispatch_patch  # noqa: E402
from .agile_alpha719_dashboard import install_alpha719_dashboard_patch  # noqa: E402
from .agile_alpha719_validation import install_alpha719_validation_patch  # noqa: E402
from .agile_alpha720_dashboard import install_alpha720_dashboard_patch  # noqa: E402
from .agile_alpha720_preinstall import install_alpha720_preinstall_patch  # noqa: E402
from .agile_alpha722_horizon import install_alpha722_price_horizon_patch  # noqa: E402
from .agile_alpha723_shadow import install_alpha723_shadow_patch  # noqa: E402
from .agile_alpha724_outcome import install_alpha724_outcome_parity_patch  # noqa: E402
from .agile_alpha725_nonzero import (  # noqa: E402
    install_alpha725_nonzero_export_proof_patch,
)
from .agile_alpha726_provisional import (  # noqa: E402
    install_alpha726_provisional_planning_patch,
)
from .agile_alpha727_price_recovery import (  # noqa: E402
    install_alpha727_price_recovery_patch,
)
from .agile_alpha728_bounded_partial import (  # noqa: E402
    install_alpha728_bounded_partial_horizon_patch,
)
from .agile_alpha729_live_routing import (  # noqa: E402
    install_alpha729_live_routing_parity_patch,
)
from .agile_alpha730_current_routing import (  # noqa: E402
    install_alpha730_current_routing_patch,
)
from .agile_alpha731_solar_headroom import (  # noqa: E402
    install_alpha731_solar_headroom_patch,
)
from .agile_alpha734_deadline_guard import (  # noqa: E402
    install_alpha734_deadline_guard_patch,
)
from .agile_alpha735_cheap_handover import (  # noqa: E402
    install_alpha735_cheap_handover_patch,
)
from .agile_alpha736_panel_flow import install_alpha736_panel_flow_patch  # noqa: E402
from .agile_alpha740_opportunity_guard import (  # noqa: E402
    install_alpha740_opportunity_guard_patch,
)
from .agile_alpha741_partial_publication import (  # noqa: E402
    install_alpha741_partial_publication_patch,
)
from .agile_alpha742_dashboard_focus import (  # noqa: E402
    install_alpha742_dashboard_focus_patch,
)
from .agile_alpha742_live_graph_telemetry import (  # noqa: E402
    install_alpha742_live_graph_telemetry_patch,
)
from .agile_alpha743_event_priority import (  # noqa: E402
    install_alpha743_event_priority_patch,
)
from .agile_alpha744_dashboard_parity import (  # noqa: E402
    install_alpha744_dashboard_parity_patch,
)
from .agile_alpha745_plan_clarity import (  # noqa: E402
    install_alpha745_plan_clarity_patch,
)
from .agile_alpha746_no_unknown_reserve import (  # noqa: E402
    install_alpha746_no_unknown_reserve_patch,
)
from .agile_alpha748_full_battery_solar import (  # noqa: E402
    install_alpha748_full_battery_solar_patch,
)
from .agile_alpha749_deadline_plan_coverage import (  # noqa: E402
    install_alpha749_deadline_plan_coverage_patch,
)
from .agile_dashboard_yaml_guard import install_dashboard_yaml_guard  # noqa: E402
from .agile_rolling_replan import install_rolling_replan_patch  # noqa: E402
from .agile_smart_export_live import install_live_scenario_patch  # noqa: E402
from .agile_smart_export_runtime_base import *  # noqa: E402,F403
from .dashboard_alpha736_finance import (  # noqa: E402
    install_alpha736_finance_dashboard_patch,
)
from .dashboard_alpha740_agile_primary import (  # noqa: E402
    install_alpha740_agile_primary_dashboard_patch,
)
from .dashboard_alpha741_partial_publication import (  # noqa: E402
    install_alpha741_partial_publication_dashboard_patch,
)
from .dashboard_consolidation import install_dashboard_consolidation  # noqa: E402

install_rolling_replan_patch()
install_live_scenario_patch()
install_dashboard_yaml_guard()
install_alpha717_dispatch_patch()
install_alpha714_dashboard_patch()
install_alpha715_dashboard_patch()
install_alpha716_dashboard_patch()
install_alpha717_dashboard_patch()
install_alpha719_validation_patch()
install_dashboard_consolidation()
install_alpha719_dashboard_patch()
install_alpha720_preinstall_patch()
install_alpha720_dashboard_patch()
install_alpha722_price_horizon_patch()
install_alpha723_shadow_patch()
install_alpha724_outcome_parity_patch()
install_alpha725_nonzero_export_proof_patch()
install_alpha726_provisional_planning_patch()
install_alpha727_price_recovery_patch()
install_alpha728_bounded_partial_horizon_patch()
install_alpha729_live_routing_parity_patch()
install_alpha730_current_routing_patch()
install_alpha731_solar_headroom_patch()
install_alpha734_deadline_guard_patch()
install_alpha735_cheap_handover_patch()
install_alpha736_panel_flow_patch()
install_alpha736_finance_dashboard_patch()
install_alpha740_opportunity_guard_patch()
install_alpha740_agile_primary_dashboard_patch()
install_alpha741_partial_publication_patch()
install_alpha741_partial_publication_dashboard_patch()
install_alpha742_dashboard_focus_patch()
install_alpha742_live_graph_telemetry_patch()
install_alpha743_event_priority_patch()
install_alpha744_dashboard_parity_patch()
install_alpha745_plan_clarity_patch()
install_alpha746_no_unknown_reserve_patch()
install_alpha748_full_battery_solar_patch()
install_alpha749_deadline_plan_coverage_patch()

EfficientAgileSmartExportManager = _base.EfficientAgileSmartExportManager


def __getattr__(name: str):
    """Delegate private runtime helpers to the preserved implementation."""
    return getattr(_base, name)
