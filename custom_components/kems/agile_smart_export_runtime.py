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
from .agile_dashboard_yaml_guard import install_dashboard_yaml_guard  # noqa: E402
from .agile_rolling_replan import install_rolling_replan_patch  # noqa: E402
from .agile_smart_export_live import install_live_scenario_patch  # noqa: E402
from .agile_smart_export_runtime_base import *  # noqa: E402,F403
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

EfficientAgileSmartExportManager = _base.EfficientAgileSmartExportManager


def __getattr__(name: str):
    """Delegate private runtime helpers to the preserved implementation."""
    return getattr(_base, name)
