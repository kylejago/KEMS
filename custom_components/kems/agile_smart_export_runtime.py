"""Canonical Agile runtime entry point.

Alpha8.0 preserves the proven Alpha7.52 behaviour through one frozen
compatibility boundary. New Alpha8 work belongs in canonical runtime modules,
not in additional version-named monkey-patch layers.
"""

from __future__ import annotations

from .agile_alpha7_compat import install_alpha7_compatibility

_base = install_alpha7_compatibility()

from .agile_smart_export_runtime_base import *  # noqa: E402,F403

EfficientAgileSmartExportManager = _base.EfficientAgileSmartExportManager


def __getattr__(name: str):
    """Delegate private runtime helpers to the preserved implementation."""
    return getattr(_base, name)
