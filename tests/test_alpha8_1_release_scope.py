"""Release-scope guards for KEMS 0.8.0-alpha8.1."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def test_alpha8_1_release_keeps_real_hardware_writes_blocked() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    shadow = (INTEGRATION / "agile_shadow_command_runtime.py").read_text(
        encoding="utf-8"
    )
    commissioning = (INTEGRATION / "commissioning.py").read_text(encoding="utf-8")

    assert manifest["version"] == "0.8.0-alpha8.1"
    assert '"hardware_writes": "blocked"' in shadow
    assert '"real_backend_available": False' in shadow
    assert '"commands_permitted": False' in shadow
    assert '"safe_to_write_hardware": False' in shadow
    assert '"ready_for_control": False' in commissioning
    assert '"maximum_allowed_stage": "shadow"' in commissioning
    assert '"real_hardware_writes": "blocked"' in commissioning
