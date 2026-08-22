"""Canonical Agile pre-install evidence and dashboard ownership.

This Alpha8 boundary retains the proven Alpha7.20 historical proposal-solar
evidence reconstruction and split shadow-readiness dashboard without rewriting
either runtime. No frozen downstream runtime imports the Alpha7.20 module names,
so no legacy module-identity bridge is required. Real hardware writes remain
blocked.
"""

from __future__ import annotations

from . import agile_preinstall_dashboard_runtime as dashboard_runtime
from . import agile_preinstall_evidence_runtime as evidence_runtime


def install_preinstall_evidence() -> None:
    """Install the proven Alpha7.20 pre-install historical evidence behaviour."""
    evidence_runtime.install_alpha720_preinstall_patch()


def install_preinstall_dashboard() -> None:
    """Install the proven Alpha7.20 pre-install dashboard behaviour."""
    dashboard_runtime.install_alpha720_dashboard_patch()
