"""Regression coverage for the managed EV policy dashboard cards."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "custom_components" / "kems" / "ev_policy_dashboard.py"
SPEC = importlib.util.spec_from_file_location("kems_ev_policy_dashboard", MODULE)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


def test_ev_policy_cards_are_added_before_current_routing() -> None:
    source = """views:\n  - title: Full KEMS Agile\n    cards:\n      - type: markdown\n        title: Current routing and today totals\n        content: |\n          existing\n"""
    result = dashboard.add_ev_policy_dashboard(source)
    assert "EV charging policy — shadow" in result
    assert "select.kems_ev_charging_policy" in result
    assert "binary_sensor.kems_ev_charging_allowed_by_control" in result
    assert "PLUGGED IN — BLOCKED BY KEMS" in result
    assert result.index("EV charging policy — shadow") < result.index(
        "Current routing and today totals"
    )


def test_ev_policy_dashboard_is_idempotent_and_reporting_only() -> None:
    source = (
        """      - type: markdown\n        title: Current routing and today totals\n"""
    )
    first = dashboard.add_ev_policy_dashboard(source)
    assert dashboard.add_ev_policy_dashboard(first) == first
    text = MODULE.read_text(encoding="utf-8")
    assert ".services.async_call(" not in text
    assert "hardware writes" not in text.lower()
    assert "Alpha8.5 is shadow policy only" in text
