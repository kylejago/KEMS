"""Alpha9.20 real shadow-status Recorder-owner regression."""

from __future__ import annotations

import ast
import copy
import json
import types
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
SHADOW_PUBLISHER = KEMS / "agile_shadow_command_runtime.py"
SHADOW_STATUS = "sensor.kems_agile_shadow_status"


def _future_annotations() -> ast.ImportFrom:
    return ast.ImportFrom(
        module="__future__",
        names=[ast.alias(name="annotations")],
        level=0,
    )


def _load_hygiene_installer(
    runtime_module: object,
    shadow_module: object,
    updater_module: object,
):
    """Execute the real helper and installer with relative imports injected."""
    tree = ast.parse(HYGIENE.read_text(encoding="utf-8"), filename=str(HYGIENE))
    helper = copy.deepcopy(
        next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_async_set_live_only_attributes"
        )
    )
    installer = copy.deepcopy(
        next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_install_manual_state_hygiene"
        )
    )

    rewritten: list[ast.stmt] = []
    module_names = {
        "agile_smart_export_runtime": ("agile_runtime", "_runtime_module"),
        "shadow_validation": ("shadow_runtime", "_shadow_module"),
        "update_orchestrator": ("updater", "_updater_module"),
    }
    for statement in installer.body:
        if isinstance(statement, ast.ImportFrom) and statement.level == 1:
            alias = statement.names[0]
            replacement = module_names.get(alias.name)
            if replacement is not None:
                expected_alias, injected_name = replacement
                assert alias.asname == expected_alias
                rewritten.append(
                    ast.Assign(
                        targets=[ast.Name(id=expected_alias, ctx=ast.Store())],
                        value=ast.Name(id=injected_name, ctx=ast.Load()),
                    )
                )
                continue
        rewritten.append(statement)
    installer.body = rewritten

    module = ast.Module(
        body=[_future_annotations(), helper, installer],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    state_info = {"unrecorded_attributes": frozenset({"*"})}
    namespace = {
        "_runtime_module": runtime_module,
        "_shadow_module": shadow_module,
        "_updater_module": updater_module,
        "AGILE_SHADOW_STATUS_ENTITY_ID": SHADOW_STATUS,
        "RECORDER_LIVE_ONLY_STATE_INFO": state_info,
    }
    exec(compile(module, str(HYGIENE), "exec"), namespace)
    return namespace["_install_manual_state_hygiene"], state_info


def _load_real_shadow_publisher():
    """Execute the production _publish_agile_shadow function unchanged."""
    tree = ast.parse(
        SHADOW_PUBLISHER.read_text(encoding="utf-8"),
        filename=str(SHADOW_PUBLISHER),
    )
    publisher = copy.deepcopy(
        next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_publish_agile_shadow"
        )
    )
    module = ast.Module(
        body=[_future_annotations(), publisher],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {}
    exec(compile(module, str(SHADOW_PUBLISHER), "exec"), namespace)
    return namespace["_publish_agile_shadow"]


def test_alpha920_real_shadow_publisher_uses_shadow_validation_recorder_owner() -> None:
    """Drive the real shadow publisher through the owner used in production."""

    class RuntimeManager:
        def _set(self, entity_id: str, value: object, attributes: dict) -> None:
            raise AssertionError("runtime manager should not own shadow publication")

    class FakeUpdateOrchestrator:
        def _write_legacy_states(self) -> None:
            pass

    class FakeStates:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict, dict]] = []

        def async_set(
            self,
            entity_id: str,
            value: str,
            attributes: dict,
            **kwargs,
        ) -> None:
            self.calls.append((entity_id, value, attributes, kwargs))

    class FakeShadowValidationRecorder:
        def _set(self, entity_id: str, value: object, attributes: dict) -> None:
            self._hass.states.async_set(entity_id, str(value), attributes)

    runtime_module = types.SimpleNamespace(
        EfficientAgileSmartExportManager=RuntimeManager
    )
    shadow_module = types.SimpleNamespace(
        ShadowValidationRecorder=FakeShadowValidationRecorder
    )
    updater_module = types.SimpleNamespace(
        KEMSUpdateOrchestrator=FakeUpdateOrchestrator
    )

    original_shadow_set = FakeShadowValidationRecorder._set
    installer, expected_state_info = _load_hygiene_installer(
        runtime_module,
        shadow_module,
        updater_module,
    )
    installer()

    patched_shadow_set = FakeShadowValidationRecorder._set
    assert patched_shadow_set is not original_shadow_set
    assert getattr(patched_shadow_set, "_kems_alpha920_recorder_hygiene", False) is True

    states = FakeStates()
    recorder = object.__new__(FakeShadowValidationRecorder)
    recorder._hass = types.SimpleNamespace(states=states)
    recorder._agile_decisions = [{"evidence": "x" * 20_000}]

    publish = _load_real_shadow_publisher()
    publish(
        recorder,
        {
            "available": True,
            "status": "PASS — shadow candidate ready",
            "dispatch_mode": "price_optimised",
            "candidate": {},
            "safety": {"passed": True},
        },
        datetime(2026, 9, 9, 22, 0, tzinfo=UTC),
    )

    status_call = next(call for call in states.calls if call[0] == SHADOW_STATUS)
    _, _, status_attributes, status_kwargs = status_call
    assert len(json.dumps(status_attributes, separators=(",", ":")).encode()) > 16_384
    assert status_attributes["recent_decisions"][0]["evidence"] == "x" * 20_000
    assert status_kwargs["state_info"] == expected_state_info

    sibling_calls = [call for call in states.calls if call[0] != SHADOW_STATUS]
    assert len(sibling_calls) == 4
    assert all("state_info" not in call[3] for call in sibling_calls)


def test_alpha920_source_binds_only_shadow_status_to_live_only_boundary() -> None:
    """Keep the fix on the actual ShadowValidationRecorder publication owner."""
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert "from . import shadow_validation as shadow_runtime" in hygiene
    assert "shadow_runtime.ShadowValidationRecorder._set" in hygiene
    assert (
        'AGILE_SHADOW_STATUS_ENTITY_ID = "sensor.kems_agile_shadow_status"' in hygiene
    )
    assert "if entity_id == AGILE_SHADOW_STATUS_ENTITY_ID:" in hygiene
    assert "shadow_set(self, entity_id, value, attributes)" in hygiene


def test_alpha920_release_scope_is_recorder_only() -> None:
    """Keep the live hotfix outside optimiser, tariff and FoxESS authority."""
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.26"
    reason = bundle["maintenance"]["reason"].lower()
    assert "shadowvalidationrecorder" in reason
    assert "recorder" in reason
    assert "forecast_path_scheduler" not in hygiene
    assert "system_profile" not in hygiene
    assert "providers.foxess" not in hygiene
    assert "commands_permitted = True" not in hygiene
    assert "safe_to_write_hardware = True" not in hygiene
