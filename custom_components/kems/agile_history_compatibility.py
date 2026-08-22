"""Canonical Agile historical-backfill compatibility ownership.

This Alpha8 boundary retains the proven Alpha7.15 Home Assistant Energy-history
schema compatibility and sensor-backed diagnostics without rewriting the runtime.
The installer mutates shared backfill functions/classes before runtime_base is
imported; no frozen downstream runtime imports the Alpha7.15 module name, so no
legacy module-identity bridge is required. Real hardware writes remain blocked.
"""

from __future__ import annotations

from . import agile_history_compatibility_runtime as history_runtime


def install_history_compatibility() -> None:
    """Install the proven Alpha7.15 historical-backfill compatibility layer."""
    history_runtime.install_alpha715_backfill_patch()
