"""Alpha9.18 live-proven Recorder startup hotfix regression."""

from __future__ import annotations

import ast
import copy
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
AGILE = KEMS / "agile_smart_export.py"


def _future_annotations() -> ast.ImportFrom:
    return ast.ImportFrom(
        module="__future__",
        names=[ast.alias(name="annotations")],
        level=0,
    )


def _load_real_agile_manager_class() -> type:
    """Execute the real manager class definition without importing Home Assistant."""
    tree = ast.parse(AGILE.read_text(encoding="utf-8"), filename=str(AGILE))
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "AgileSmartExportManager" in class_names
    assert "EfficientAgileSmartExportManager" not in class_names
    manager = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    module = ast.Module(
        body=[_future_annotations(), copy.deepcopy(manager)],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {}
    exec(compile(module, str(AGILE), "exec"), namespace)
    return namespace["AgileSmartExportManager"]  # type: ignore[return-value]


def _load_manual_hygiene_installer(
    agile_module: object,
    updater_module: object,
    publisher: object,
):
    """Execute the real installer body with only its relative imports injected."""
    tree = ast.parse(HYGIENE.read_text(encoding="utf-8"), filename=str(HYGIENE))
    installer = copy.deepcopy(
        next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_install_manual_state_hygiene"
        )
    )

    rewritten: list[ast.stmt] = []
    for statement in installer.body:
        if isinstance(statement, ast.ImportFrom) and statement.level == 1:
            alias = statement.names[0]
            if alias.name == "agile_smart_export" and alias.asname == "agile":
                rewritten.append(
                    ast.Assign(
                        targets=[ast.Name(id="agile", ctx=ast.Store())],
                        value=ast.Name(id="_agile_module", ctx=ast.Load()),
                    )
                )
                continue
            if alias.name == "update_orchestrator" and alias.asname == "updater":
                rewritten.append(
                    ast.Assign(
                        targets=[ast.Name(id="updater", ctx=ast.Store())],
                        value=ast.Name(id="_updater_module", ctx=ast.Load()),
                    )
                )
                continue
        rewritten.append(statement)
    installer.body = rewritten

    module = ast.Module(
        body=[_future_annotations(), installer],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {
        "_agile_module": agile_module,
        "_updater_module": updater_module,
        "_async_set_live_only_attributes": publisher,
    }
    exec(compile(module, str(HYGIENE), "exec"), namespace)
    return namespace["_install_manual_state_hygiene"]


def test_alpha918_installer_patches_real_agile_manager_and_publishes_state_info() -> (
    None
):
    """The startup installer must patch the class HA actually imports and uses."""
    manager_class = _load_real_agile_manager_class()
    original_set = manager_class._set
    agile_module = types.SimpleNamespace(AgileSmartExportManager=manager_class)

    class FakeUpdateOrchestrator:
        def _write_legacy_states(self) -> None:
            pass

    updater_module = types.SimpleNamespace(
        KEMSUpdateOrchestrator=FakeUpdateOrchestrator
    )
    published: list[tuple[object, str, object, dict[str, object]]] = []

    def publisher(
        hass: object,
        entity_id: str,
        value: object,
        attributes: dict[str, object],
    ) -> None:
        published.append((hass, entity_id, value, attributes))

    installer = _load_manual_hygiene_installer(
        agile_module,
        updater_module,
        publisher,
    )
    installer()

    patched_set = manager_class._set
    assert patched_set is not original_set
    assert getattr(patched_set, "_kems_alpha917_recorder_hygiene", False) is True

    manager = object.__new__(manager_class)
    hass = object()
    manager._hass = hass
    attributes = {"today_slots": [{"detail": "rich live payload"}]}
    patched_set(
        manager,
        "sensor.kems_agile_smart_export_plan",
        "hold",
        attributes,
    )
    assert published == [
        (
            hass,
            "sensor.kems_agile_smart_export_plan",
            "hold",
            attributes,
        )
    ]


def test_alpha918_hotfix_is_only_the_manager_target_and_release_identity() -> None:
    """Keep the hotfix narrow and retain the Alpha9.17 Recorder boundary."""
    hygiene = HYGIENE.read_text(encoding="utf-8")
    manifest = (KEMS / "manifest.json").read_text(encoding="utf-8")
    assert "agile.AgileSmartExportManager._set" in hygiene
    assert "agile.EfficientAgileSmartExportManager._set" not in hygiene
    assert '"version": "0.9.0-alpha9.18"' in manifest
    assert "forecast_path_scheduler" not in hygiene
    assert "system_profile" not in hygiene
    assert "commands_permitted = True" not in hygiene
    assert "safe_to_write_hardware = True" not in hygiene
