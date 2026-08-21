"""Regression coverage for Alpha7.46 no-reserve Agile publication planning."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha746_no_unknown_reserve.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "alpha746-agile-no-unknown-reserve.md"


def test_alpha746_release_version_keeps_web20_and_panel7() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.7.0-alpha7.46"
    assert bundle["components"]["property_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["pi_agent"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["public_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel7"


def test_alpha746_module_parses_and_installs_after_alpha745() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))
    loader = LOADER.read_text(encoding="utf-8")

    assert "install_alpha746_no_unknown_reserve_patch" in loader
    assert loader.rindex("install_alpha746_no_unknown_reserve_patch()") > loader.rindex(
        "install_alpha745_plan_clarity_patch()"
    )


def test_alpha746_keeps_full_known_price_plan_and_reserves_zero() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "def _no_reserve_unknown_capacity(" in source
    assert "return [dict(item) for item in selected if isinstance(item, dict)], 0.0" in source
    assert "alpha726._reserve_unknown_capacity = _no_reserve_unknown_capacity" in source
    assert '"provisional_reserved_unknown_capacity_kwh": 0.0' in source
    assert '"bounded_unknown_capacity_reserved_kwh": 0.0' in source
    assert '"unknown_price_reservation_policy": "none"' in source
    assert "replan_when_price_publishes" in source


def test_alpha746_only_relaxes_clean_publication_gaps() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert 'recovery.get("publication_pending")' in source
    assert 'recovery.get("verified")' in source
    assert 'horizon.get("current_slot_known")' in source
    assert 'current_price.get("known")' in source
    assert "alpha746_original_apply(" in source


def test_alpha746_dashboard_explains_no_reserve_and_reranking() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "Capacity reserved for unpublished slots | **0.0 kWh**" in source
    assert "no capacity reserved; re-rank when" in source
    assert "known_price_plan_coverage_percent" in source
    assert "may replace lower-value future export slots" in source


def test_alpha746_preserves_safety_and_no_hardware_writes() -> None:
    source = PATCH.read_text(encoding="utf-8")
    docs = DOC.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "current settlement period must still have a real published price" in docs
    assert "10% target" in docs
    assert "Power Down priority" in docs
    assert "Happy Hour priority" in docs
    assert "Real FoxESS hardware writes remain blocked" in docs
