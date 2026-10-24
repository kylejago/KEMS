"""Alpha9.128 release identity and strictly read-only historical acceleration."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_alpha9128_manifest_bundle_and_replay_scope() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    reason = str(bundle["maintenance"]["reason"]).lower()
    assert manifest["version"] == "0.9.0-alpha9.133"
    assert reason.startswith("alpha9.133:")
    assert "current and tomorrow" in reason
    assert "physical/ev/dno/export safety authority unchanged" in reason


def test_alpha9128_never_throttles_live_rolling_or_physical_guard() -> None:
    runtime = (KEMS / "agile_smart_export_runtime_base.py").read_text()
    rolling = (KEMS / "agile_rolling_replan_runtime.py").read_text()
    cache = (KEMS / "kems_core" / "agile_historical_replay_cache.py").read_text()
    budget = (KEMS / "kems_core" / "agile_plan_budget_reconciliation.py").read_text()
    assert "runtime.ANALYSIS_REFRESH = timedelta(0)" in rolling
    assert "if today is None or day >= today or projection:" in cache
    assert "return calculate()" in cache
    assert "cache.evaluate(" in runtime
    assert "hardware_writes" not in runtime
    assert '"hardware_writes": "blocked"' in budget
