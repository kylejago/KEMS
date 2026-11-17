"""Regression contracts for Alpha9.27 policy-label publication."""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLARITY = ROOT / "custom_components" / "kems" / "agile_observability_clarity.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
RELEASE_TEMPLATE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha927_final_publication_owns_house_bridge_label() -> None:
    source = CLARITY.read_text(encoding="utf-8")

    assert 'rolling["dispatch_action"] = action' in source
    assert 'state["current_action"] = action' in source
    assert "deliberate-export target reached" in source
    assert "floor until cheap charge; no deliberate export" in source
    assert "10% planning target reached" not in source
    assert "10% reserve floor — no battery discharge/export" not in source

    publish = source.split("def publish_with_observability_clarity", 1)[1]
    assert publish.count("_clarify_policy_action_labels(state)") >= 2
    assert publish.index("_original_publish(self, state)") < publish.rindex(
        "_clarify_policy_action_labels(state)"
    )


def test_alpha927_is_reporting_only_and_keeps_panel_profile_release() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(RELEASE_TEMPLATE.read_text(encoding="utf-8"))
    maintenance = bundle["maintenance"]
    reason = maintenance["reason"]

    assert manifest["version"] == "0.9.0-alpha9.217"
    assert "reporting-only" in reason.lower()
    assert "policy" in reason.lower()
    assert "15%" in reason
    assert "10% absolute floor" in reason
    assert "12%" in reason
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.4"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["public_web"]["version"] == "0.9.0-alpha9-public.0"
    assert "hardware writes remain hard-blocked" in reason


def _live_label_helper():
    """Isolate reporting-only label functions without Home Assistant imports."""
    source = CLARITY.read_text(encoding="utf-8")
    module = ast.parse(source)
    names = {
        "_number",
        "_percent_text",
        "_house_bridge_action",
        "_pre_target_home_action",
        "_clarify_policy_action_labels",
    }
    body = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    scope = {
        "Any": Any,
        "math": math,
        "_EPSILON": 1e-6,
        "PLANNING_TARGET_SOC_PERCENT": 15.0,
        "HARD_SAFETY_FLOOR_SOC_PERCENT": 10.0,
        "HARD_SAFETY_RECOVERY_SOC_PERCENT": 12.0,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(CLARITY), "exec"), scope)
    return scope["_clarify_policy_action_labels"]


def test_explicit_physical_plan_not_reached_overrides_simulated_soc_and_stale_text():
    old = (
        "15% deliberate-export target reached — house-only battery bridge "
        "toward 10% absolute floor until cheap charge; no deliberate export"
    )
    state = {
        "rolling_export_plan": {
            "planning_target_reached": False,
            "planning_target_soc_percent": 15.0,
            "planning_soc_percent": 22.14,
            "simulated_soc_percent": 7.983,
            "dispatch_mode": "target_reached",
            "dispatch_action": old,
            "current_house_battery_kw": 1.334,
            "current_battery_export_target_kw": 0.0,
        },
        "current_action": old,
        "today_action": old,
        "current_routing_snapshot": {
            "dispatch_mode": "target_reached",
            "routing_action": old,
            "simulated_soc_percent": 7.983,
            "battery_to_home_kw": 1.334,
            "battery_export_kw": 0.0,
        },
        "today_slots": [],
    }
    original_soc = state["rolling_export_plan"]["planning_soc_percent"]
    _live_label_helper()(state)
    assert "target not reached" in state["current_action"]
    assert state["current_action"] == state["today_action"]
    assert state["rolling_export_plan"]["dispatch_action"] == state["current_action"]
    assert (
        state["current_routing_snapshot"]["routing_action"] == state["current_action"]
    )
    assert state["rolling_export_plan"]["planning_soc_percent"] == original_soc
    assert state["rolling_export_plan"]["dispatch_mode"] == "target_reached"


def test_explicit_physical_plan_reached_keeps_house_bridge():
    state = {
        "rolling_export_plan": {
            "planning_target_reached": True,
            "planning_target_soc_percent": 15.0,
            "simulated_soc_percent": 22.0,
            "current_house_battery_kw": 0.9,
            "current_battery_export_target_kw": 0.0,
        },
        "today_slots": [],
    }
    _live_label_helper()(state)
    assert "15% deliberate-export target reached" in state["current_action"]
