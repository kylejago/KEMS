"""Regression contracts for Alpha9.27 policy-label publication."""

from __future__ import annotations

import json
from pathlib import Path

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

    assert manifest["version"] == "0.9.0-alpha9.30"
    assert "reporting-only" in reason.lower()
    assert "policy" in reason.lower()
    assert "15%" in reason
    assert "10% absolute floor" in reason
    assert "12%" in reason
    assert "0.9.0-alpha9-panel.3" in reason
    assert "0.9.0-alpha9-web.0" in reason
    assert "0.9.0-alpha9-public.0" in reason
    assert "hardware writes hard-blocked" in reason
