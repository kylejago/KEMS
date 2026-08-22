"""Canonical Alpha8 product-presentation installer for proven Alpha7.36 reporting.

This boundary owns the reporting-only panel flow projection and the finance/
comparison dashboard presentation. It does not alter planning, optimisation,
tariffs, commissioning, or real hardware write permissions.
"""

from __future__ import annotations

from . import agile_panel_presentation_runtime as panel_runtime
from . import dashboard_product_finance_runtime as dashboard_runtime


def install_product_presentation() -> None:
    """Install panel projection first, then finance/dashboard presentation."""
    panel_runtime.install_alpha736_panel_flow_patch()
    dashboard_runtime.install_alpha736_finance_dashboard_patch()
