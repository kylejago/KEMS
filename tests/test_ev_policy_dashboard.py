"""Regression coverage for the managed EV policy dashboard cards."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
MODULE = KEMS / "ev_policy_dashboard.py"
CONSOLIDATION = KEMS / "dashboard_consolidation.py"

SPEC = importlib.util.spec_from_file_location("kems_ev_policy_dashboard", MODULE)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

CONSOLIDATION_SPEC = importlib.util.spec_from_file_location(
    "kems_dashboard_consolidation", CONSOLIDATION
)
assert CONSOLIDATION_SPEC is not None and CONSOLIDATION_SPEC.loader is not None
consolidation = importlib.util.module_from_spec(CONSOLIDATION_SPEC)
CONSOLIDATION_SPEC.loader.exec_module(consolidation)


def _source_dashboard() -> str:
    parts = ["title: KEMS Master Dashboard\n\nviews:\n"]
    for index, title in enumerate(sorted(consolidation.EXPECTED_SOURCE_TITLES)):
        parts.append(
            f"  - title: {title}\n"
            f"    path: source-{index}\n"
            "    icon: mdi:test-tube\n"
            "    cards:\n"
            "      - type: markdown\n"
            "        content: |\n"
            f"          {title}\n"
        )
    return "".join(parts)


def test_ev_policy_cards_insert_into_real_consolidated_agile_view() -> None:
    consolidated = consolidation.consolidate_dashboard(_source_dashboard())
    result = dashboard.add_ev_policy_dashboard(consolidated)

    agile = result.split("  - title: Full KEMS Agile\n", 1)[1].split(
        "  - title: Compare\n", 1
    )[0]
    assert "EV charging policy — shadow" in agile
    assert "select.kems_ev_charging_policy" in agile
    assert "binary_sensor.kems_ev_charging_allowed_by_control" in agile
    assert "PLUGGED IN — BLOCKED BY KEMS" in agile


def test_missing_agile_view_never_blocks_dashboard_generation() -> None:
    source = "title: KEMS Master Dashboard\n\nviews:\n"
    assert dashboard.add_ev_policy_dashboard(source) == source


def test_ev_policy_dashboard_is_idempotent_and_reporting_only() -> None:
    consolidated = consolidation.consolidate_dashboard(_source_dashboard())
    first = dashboard.add_ev_policy_dashboard(consolidated)
    assert dashboard.add_ev_policy_dashboard(first) == first
    text = MODULE.read_text(encoding="utf-8")
    assert ".services.async_call(" not in text
    assert "providers.ohme" not in text
    assert "providers.foxess" not in text
    assert "EV policy is shadow-only" in text


def test_integration_setup_catches_dashboard_value_errors() -> None:
    source = (KEMS / "__init__.py").read_text(encoding="utf-8")
    assert "except (OSError, ValueError):" in source
    assert "continuing KEMS setup" in source
