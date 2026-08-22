"""Canonical Full KEMS Agile operator telemetry installation boundary.

This Alpha8 module owns the proven Alpha7.42 focused dashboard and live graph
telemetry installation order without keeping either version-named module in the
executable compatibility registry.

The two canonical runtime owners remain byte-for-byte identical to their
historical Alpha7.42 implementations in this parity slice. The dashboard focus
is installed first, then the live graph mirror, preserving the exact runtime
wrapping and dashboard transformation order.

This boundary is reporting-only. Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

from . import agile_live_graph_runtime as live_graph
from . import agile_operator_dashboard_runtime as operator_dashboard


def install_operator_telemetry() -> None:
    """Install the canonical focused operator telemetry in historical order."""
    operator_dashboard.install_alpha742_dashboard_focus_patch()
    live_graph.install_alpha742_live_graph_telemetry_patch()
