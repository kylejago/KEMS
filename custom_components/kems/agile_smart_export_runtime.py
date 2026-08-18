"""Efficient Agile runtime loader with solar-routing reporting fixes."""

from __future__ import annotations

from .agile_smart_export_reporting import install_reporting_patch

install_reporting_patch()

from . import agile_smart_export_runtime_base as _base  # noqa: E402
from .agile_dashboard_yaml_guard import install_dashboard_yaml_guard  # noqa: E402
from .agile_smart_export_live import install_live_scenario_patch  # noqa: E402
from .agile_smart_export_runtime_base import *  # noqa: E402,F403

install_live_scenario_patch()
install_dashboard_yaml_guard()

EfficientAgileSmartExportManager = _base.EfficientAgileSmartExportManager


def __getattr__(name: str):
    """Delegate private runtime helpers to the preserved implementation."""
    return getattr(_base, name)
