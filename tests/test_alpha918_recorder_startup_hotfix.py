"""Alpha9.18 historical Recorder startup-hotfix regression."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
AGILE = KEMS / "agile_smart_export.py"


def test_alpha918_base_manager_name_remains_valid() -> None:
    """Retain proof for the Alpha9.17 startup crash fixed by Alpha9.18."""
    tree = ast.parse(AGILE.read_text(encoding="utf-8"), filename=str(AGILE))
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert "AgileSmartExportManager" in class_names
    assert "EfficientAgileSmartExportManager" not in class_names


def test_alpha918_nonexistent_base_module_target_never_returns() -> None:
    """The exact Alpha9.17 nonexistent-class typo must stay removed."""
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert "agile.EfficientAgileSmartExportManager._set" not in hygiene
    assert "forecast_path_scheduler" not in hygiene
    assert "system_profile" not in hygiene
    assert "commands_permitted = True" not in hygiene
    assert "safe_to_write_hardware = True" not in hygiene
