"""Canonical live house-demand routing ownership.

This Alpha8 boundary retains the proven Alpha7.29 reporting-only parity behaviour
without rewriting its live house-load publication, diagnostic evidence, dashboard
labelling, or fallback semantics. Alpha7.30/Alpha7.31 remain outside this seam.
"""

from __future__ import annotations

from . import agile_live_routing_runtime as live_routing_runtime


def install_live_routing() -> None:
    """Install the proven live house-demand routing parity."""
    live_routing_runtime.install_alpha729_live_routing_parity_patch()
