"""Canonical latest-safe-start deadline guard ownership.

This Alpha8 boundary retains the proven Alpha7.34 deadline/dispatch behaviour
without rewriting its solar-aware shared-inverter capacity model, escalation
policy, or historical Alpha7.31/Alpha7.17 dependencies. Real hardware writes
remain blocked behind the existing commissioning and backend gates.
"""

from __future__ import annotations

from . import agile_deadline_guard_runtime as deadline_runtime


def install_deadline_guard() -> None:
    """Install the proven latest-safe-start deadline guard."""
    deadline_runtime.install_alpha734_deadline_guard_patch()
