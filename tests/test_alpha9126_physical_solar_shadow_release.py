"""Alpha9.126 release: physical solar economics stay non-controlling."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_alpha9126_release_description_is_coordinated_and_shadow_only() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    reason = str(bundle["maintenance"]["reason"]).lower()
    assert manifest["version"] == "0.9.0-alpha9.132"
    assert reason.startswith("alpha9.132")
    assert "shadow-only" in reason
    assert "no change to live inverter work-mode commands" in reason
    assert "7 kw" in reason


def test_alpha9126_solar_shadow_never_feeds_foxess_commands() -> None:
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    shadow = (KEMS / "solar_routing_shadow.py").read_text(encoding="utf-8")
    live = (KEMS / "kems_core" / "control_write_authority.py").read_text(
        encoding="utf-8"
    )
    backend = (KEMS / "foxess_control_backend.py").read_text(encoding="utf-8")
    assert "publish_solar_routing_shadow(" in coordinator
    assert "hardware_writes" in shadow and '"forbidden"' in shadow
    assert "divertible_solar_charge_kw" in shadow
    assert "physical_ac_balance_residual_kw" in shadow
    assert "solar_routing_shadow" not in live
    assert "solar_routing_shadow" not in backend
