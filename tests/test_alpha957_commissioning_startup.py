"""Alpha9.57 commissioning first-refresh startup hotfix regressions."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
RUNTIME = KEMS / "agile_runtime_reconciliation.py"
REPORTING = KEMS / "alpha947_reporting_consistency.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha957_commissioning_wrappers_forward_data_override() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    reporting = REPORTING.read_text(encoding="utf-8")

    assert "data_override: Any | None = None" in runtime
    assert runtime.count("data_override=data_override") >= 2
    assert (
        "data = data_override if data_override is not None else coordinator.data"
        in runtime
    )
    assert "data_override: Any | None = None" in reporting
    assert "data_override=data_override" in reporting
    assert "Real inverter writes remain hard-blocked until" not in reporting


def test_alpha957_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.65"
    assert (
        "Alpha9.57 fixes the first-refresh startup regression exposed immediately "
        "after installing Alpha9.56" in reason
    )
    assert "provisional data_override payload" in reason
    assert "does not broaden FoxESS write authority" in reason
    assert "10 W grid-import-prevention bias Shadow-only" in reason
