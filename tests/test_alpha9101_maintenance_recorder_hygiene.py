"""Alpha9.101: protect maintenance notice history without changing live KEMS."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
UPDATER = KEMS / "update_orchestrator.py"
RECORDER_ATTRIBUTE_LIMIT = 16_384


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _wrapper_class() -> ast.ClassDef:
    """The protected entity is a nested wrapper inside the setup installer."""
    tree = ast.parse(_source(HYGIENE), filename=str(HYGIENE))
    installer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "install_alpha917_recorder_hygiene"
    )
    return next(
        node
        for node in installer.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RecorderSafeMaintenanceStatusSensor"
    )


def test_maintenance_sensor_is_replaced_by_recorder_safe_entity_on_setup() -> None:
    source = _source(HYGIENE)
    updater = _source(UPDATER)
    wrapper = _wrapper_class()
    assert len(wrapper.bases) == 1
    assert ast.unparse(wrapper.bases[0]) == "updater.KEMSMaintenanceStatusSensor"
    assert "elif isinstance(entity, updater.KEMSMaintenanceStatusSensor):" in source
    assert "RecorderSafeMaintenanceStatusSensor(" in source
    assert 'super().__init__(coordinator, "maintenance_status")' in updater
    assert 'KEMSMaintenanceStatusSensor(coordinator, orchestrator)' in updater
    assert 'return str(self.orchestrator.maintenance.get("status") or "none")' in updater
    assert "return dict(self.orchestrator.maintenance)" in updater


def test_maintenance_wrapper_excludes_all_rich_attributes_from_recorder() -> None:
    wrapper = _wrapper_class()
    attribute = next(
        node
        for node in wrapper.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_unrecorded_attributes"
            for target in node.targets
        )
    )
    assert isinstance(attribute.value, ast.Name)
    assert attribute.value.id == "RECORDER_LIVE_ONLY_ATTRIBUTES"
    assert "RECORDER_LIVE_ONLY_ATTRIBUTES = frozenset({MATCH_ALL})" in _source(
        HYGIENE
    )

    maintenance = {
        "status": "completed",
        "reason": "KEMS release verified",
        "components": [{"name": f"component-{n}", "data": "x" * 1_000} for n in range(28)],
        "latest_bundle": {"description": "y" * 12_000},
    }
    assert len(json.dumps(maintenance).encode()) > RECORDER_ATTRIBUTE_LIMIT
    # Home Assistant MATCH_ALL records the state and standard metadata only.
    # The full mapping still exists live for dashboard and diagnostic consumers.
    live = dict(maintenance)
    stored = {"friendly_name": "KEMS Maintenance status"}
    assert live == maintenance
    assert len(json.dumps(stored).encode()) < RECORDER_ATTRIBUTE_LIMIT
    assert maintenance["status"] == "completed"


def test_maintenance_recorder_repair_cannot_modify_updates_or_live_energy() -> None:
    code = _source(HYGIENE)
    wrapper = _wrapper_class()
    assert all(
        isinstance(node, (ast.Expr, ast.Assign))
        for node in wrapper.body
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in wrapper.body
    )
    assert "updater.KEMSUpdateOrchestrator._write_legacy_states" in code
    for forbidden in (
        "foxess_control_backend",
        "_control.plan(",
        "_scenarios.compare(",
        "async_apply_pending(",
        "backup.create_automatic",
        "settings.simulation",
    ):
        assert forbidden not in code
