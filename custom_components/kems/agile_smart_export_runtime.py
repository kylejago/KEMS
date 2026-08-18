"""Efficient Agile runtime loader with solar-routing reporting fixes."""

from __future__ import annotations

from .agile_smart_export_reporting import install_reporting_patch

install_reporting_patch()

from . import agile_smart_export_runtime_base as _base  # noqa: E402
from .agile_smart_export_runtime_base import *  # noqa: E402,F403

EfficientAgileSmartExportManager = _base.EfficientAgileSmartExportManager


def __getattr__(name: str):
    """Delegate private runtime helpers to the preserved implementation."""
    return getattr(_base, name)
