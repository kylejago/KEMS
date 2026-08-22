"""Canonical Agile live-scenario reporting and dashboard YAML ownership.

This Alpha8 boundary retains the proven live-scenario reporting/dashboard layer
and its immediately-following YAML indentation guard without rewriting either
runtime. The guard is intentionally installed at its historical position because
the frozen live dashboard appender preserves the original root-level indentation
shape that the guard repairs. No legacy module-name bridge is required. Real
hardware writes remain blocked.
"""

from __future__ import annotations

from importlib import import_module

from . import agile_live_scenario_runtime as live_runtime


def install_live_scenario() -> None:
    """Install the proven Agile live-scenario reporting/dashboard layer."""
    live_runtime.install_live_scenario_patch()


def install_live_scenario_yaml_guard() -> None:
    """Install the proven final YAML indentation guard."""
    guard_runtime = import_module(
        ".agile_live_scenario_yaml_guard_runtime",
        __package__,
    )
    guard_runtime.install_dashboard_yaml_guard()
