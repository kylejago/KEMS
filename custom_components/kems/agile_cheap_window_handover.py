"""Canonical cheap-window reporting handover ownership.

This Alpha8 boundary retains the proven Alpha7.35 operator-facing handover at
the configured overnight cheap-window transition. It is reporting-only: the
Alpha7.34 deadline/dispatch policy remains authoritative, optimisation is not
changed, and real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

from . import agile_cheap_window_handover_runtime as handover_runtime


def install_cheap_window_handover() -> None:
    """Install the proven cheap-window reporting handover."""
    handover_runtime.install_alpha735_cheap_handover_patch()
