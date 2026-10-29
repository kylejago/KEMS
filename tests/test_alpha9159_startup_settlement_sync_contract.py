"""Alpha9.160: preserve the synchronous settlement MRO after 9.158 regression."""

from __future__ import annotations

import ast
import json
from pathlib import Path

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"
ROOT = KEMS.parents[1]

OWNER_METHODS = (
    ("agile_current_day_settlement.py", "SettledCurrentDayAgileSmartExportManager"),
    ("agile_midnight_rollover.py", "MidnightRolloverAgileSmartExportManager"),
    ("agile_flow_presentation.py", "FlowPresentationAgileSmartExportManager"),
    (
        "agile_canonical_flow_accounting.py",
        "CanonicalFlowAccountingAgileSmartExportManager",
    ),
    (
        "agile_live_solar_soc_continuity.py",
        "LiveSolarSocContinuityAgileSmartExportManager",
    ),
    (
        "agile_deadline_settlement_consistency.py",
        "DeadlineSettlementConsistencyAgileSmartExportManager",
    ),
)


def test_every_settlement_owner_has_a_synchronous_override() -> None:
    """Catch the precise async-base/sync-wrapper incompatibility from 9.158."""
    for filename, classname in OWNER_METHODS:
        module = ast.parse((KEMS / filename).read_text(encoding="utf-8"))
        cls = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == classname
        )
        method = next(
            node
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "reconcile_current_day_settlements"
        )
        assert isinstance(
            method, ast.FunctionDef
        ), f"{filename}:{classname} must preserve the synchronous MRO contract"
        assert not any(isinstance(n, ast.Await) for n in ast.walk(method))


def test_settlement_handoff_and_coordinator_preserve_sync_calls() -> None:
    helper = (KEMS / "agile_settled_soc_handoff.py").read_text(encoding="utf-8")
    tree = ast.parse(helper)
    handoff = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "refresh_tomorrow_handoff_from_settled_soc"
    )
    assert isinstance(handoff, ast.FunctionDef)
    assert "tomorrow = manager._compare_day(" in helper
    assert "manager._publish(manager._state)" in helper
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    assert (
        "pre_settlement = self._agile_smart_export.reconcile_current_day_settlements("
        in coordinator
    )
    assert (
        "await self._agile_smart_export.reconcile_current_day_settlements("
        not in coordinator
    )
    assert "if post_shadow_settlement_changed:" in coordinator
    assert "guard_paid_agile_physical_export(" in coordinator


def test_hotfix_release_explains_reversion_and_preserves_safety() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.9.0-alpha9.160"
    reason = bundle["maintenance"]["reason"]
    assert reason.startswith("Alpha9.160:")
    assert "Alpha9.158" in reason
    assert "7 kW" in reason
    assert "10%" in reason
