"""Canonical product-presentation installers for reporting-only KEMS surfaces.

This boundary owns panel flow projection, finance/comparison dashboard
presentation, and the Agile slot replay presentation adapter. It does not alter planning,
optimisation, tariffs, commissioning, or real hardware write permissions.
"""

from __future__ import annotations

from . import agile_panel_presentation_runtime as panel_runtime
from . import dashboard_product_finance_runtime as dashboard_runtime
from .agile_slot_simulation_fallback import install_agile_slot_simulation_fallback


def install_product_presentation() -> None:
    """Install reporting-only product presentation adapters."""
    panel_runtime.install_alpha736_panel_flow_patch()
    dashboard_runtime.install_alpha736_finance_dashboard_patch()
    install_agile_slot_simulation_fallback()
