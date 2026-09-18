"""Alpha9.58 battery-direction commissioning fallback contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMMISSIONING = KEMS / "commissioning.py"
EVIDENCE = KEMS / "kems_core" / "commissioning_evidence.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha958_commissioning_uses_read_only_balance_direction_fallback() -> None:
    commissioning = COMMISSIONING.read_text(encoding="utf-8")
    evidence = EVIDENCE.read_text(encoding="utf-8")

    assert "infer_battery_power_convention_from_balance" in commissioning
    assert "direction_conflict" in commissioning
    assert '"battery_direction_balance_evidence"' in commissioning
    assert "minimum_evidence_samples: int = 3" in evidence
    assert "minimum_battery_power_kw: float = 0.25" in evidence
    assert "minimum_confidence_percent: float = 75.0" in evidence
    assert "minimum_residual_separation_kw: float = 0.15" in evidence
    assert ".services.async_call(" not in evidence
    assert "commands_permitted = True" not in evidence


def test_alpha958_release_identity_and_safety_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.58"
    assert reason.startswith(
        "Alpha9.58 removes the large-battery integer-SOC commissioning delay"
    )
    assert "requires at least three consistent samples" in reason
    assert "fails closed if later SOC-movement evidence disagrees" in reason
    assert "does not broaden FoxESS write authority" in reason
    assert "10 W grid-import-prevention bias outside live control" in reason
