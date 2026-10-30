"""Alpha9.19 final-runtime Recorder owner regression."""

from __future__ import annotations

import ast
import copy
import json
import types
from pathlib import Path

from kems_core.settlement_publication_coalescing import (
    coalesce_identical_settlement_publications,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
COORDINATOR = KEMS / "coordinator.py"

MANUAL_AGILE_RUNTIME_OVERFLOW_ENTITIES = (
    "sensor.kems_agile_smart_export_plan",
    "sensor.kems_agile_rolling_export_plan",
    "sensor.kems_agile_decision_audit",
    "sensor.kems_agile_slot_decisions_today",
)


def _future_annotations() -> ast.ImportFrom:
    return ast.ImportFrom(
        module="__future__",
        names=[ast.alias(name="annotations")],
        level=0,
    )


def _load_manual_hygiene_installer(
    runtime_module: object,
    shadow_module: object,
    updater_module: object,
    publisher: object,
):
    """Execute the real installer body with its relative imports injected."""
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
            if (
                alias.name == "agile_smart_export_runtime"
                and alias.asname == "agile_runtime"
            ):
                rewritten.append(
                    ast.Assign(
                        targets=[ast.Name(id="agile_runtime", ctx=ast.Store())],
                        value=ast.Name(id="_runtime_module", ctx=ast.Load()),
                    )
                )
                continue
            if alias.name == "shadow_validation" and alias.asname == "shadow_runtime":
                rewritten.append(
                    ast.Assign(
                        targets=[ast.Name(id="shadow_runtime", ctx=ast.Store())],
                        value=ast.Name(id="_shadow_module", ctx=ast.Load()),
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
        "_runtime_module": runtime_module,
        "_shadow_module": shadow_module,
        "_updater_module": updater_module,
        "_async_set_live_only_attributes": publisher,
        "AGILE_SHADOW_STATUS_ENTITY_ID": "sensor.kems_agile_shadow_status",
    }
    exec(compile(module, str(HYGIENE), "exec"), namespace)
    return namespace["_install_manual_state_hygiene"]


def test_alpha919_patches_same_final_runtime_owner_used_by_coordinator() -> None:
    """The installer must patch the exact manager class KEMSCoordinator creates."""
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert "from .agile_smart_export_runtime import" in coordinator
    assert "EfficientAgileSmartExportManager" in coordinator
    assert "self._agile_smart_export = EfficientAgileSmartExportManager(" in coordinator
    assert "from . import agile_smart_export_runtime as agile_runtime" in hygiene
    assert "agile_runtime.EfficientAgileSmartExportManager._set" in hygiene
    assert "agile.AgileSmartExportManager._set" not in hygiene


def test_alpha919_runtime_owner_publishes_four_live_only_runtime_states() -> None:
    """Keep Alpha9.19 proof scoped to states owned by the final Agile manager."""

    class RuntimeManager:
        def _set(self, entity_id: str, value: object, attributes: dict) -> None:
            raise AssertionError("unpatched runtime publication")

    original_set = RuntimeManager._set
    runtime_module = types.SimpleNamespace(
        EfficientAgileSmartExportManager=RuntimeManager
    )

    class FakeShadowValidationRecorder:
        def _set(self, entity_id: str, value: object, attributes: dict) -> None:
            pass

    shadow_module = types.SimpleNamespace(
        ShadowValidationRecorder=FakeShadowValidationRecorder
    )

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
        runtime_module,
        shadow_module,
        updater_module,
        publisher,
    )
    installer()

    patched_set = RuntimeManager._set
    assert patched_set is not original_set
    assert getattr(patched_set, "_kems_alpha919_recorder_hygiene", False) is True

    manager = object.__new__(RuntimeManager)
    hass = object()
    manager._hass = hass
    attributes = {"rich_live_payload": "x" * 20_000}
    for entity_id in MANUAL_AGILE_RUNTIME_OVERFLOW_ENTITIES:
        patched_set(manager, entity_id, "live", attributes)

    assert [item[1] for item in published] == list(
        MANUAL_AGILE_RUNTIME_OVERFLOW_ENTITIES
    )
    assert all(item[0] is hass for item in published)
    assert all(item[3] is attributes for item in published)


def test_alpha919_recorder_boundary_keeps_match_all_state_info() -> None:
    """The runtime owner must still flow through HA's MATCH_ALL Recorder boundary."""
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert "RECORDER_LIVE_ONLY_ATTRIBUTES = frozenset({MATCH_ALL})" in hygiene
    assert '"unrecorded_attributes": RECORDER_LIVE_ONLY_ATTRIBUTES' in hygiene
    assert "state_info=RECORDER_LIVE_ONLY_STATE_INFO" in hygiene


def test_alpha919_release_scope_is_recorder_only() -> None:
    """Keep successor releases outside optimiser, tariff and FoxESS authority."""
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    hygiene = HYGIENE.read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.161"
    assert "runtime" in bundle["maintenance"]["reason"].lower()
    assert "recorder" in bundle["maintenance"]["reason"].lower()
    assert "forecast_path_scheduler" not in hygiene
    assert "system_profile" not in hygiene
    assert "providers.foxess" not in hygiene
    assert "commands_permitted = True" not in hygiene
    assert "safe_to_write_hardware = True" not in hygiene


def test_alpha9162_effective_recorder_publisher_honours_settlement_scope() -> None:
    """Exercise the real installer rather than only the overridden base setter."""

    class RuntimeManager:
        def _set(self, entity_id, value, attributes):
            raise AssertionError("obsolete base setter must not be called")

    class Shadow:
        def _set(self, entity_id, value, attributes):
            pass

    class Updater:
        def _write_legacy_states(self):
            pass

    class States:
        def __init__(self):
            self.data = {}
            self.writes = []

        def get(self, entity_id):
            return self.data.get(entity_id)

    states = States()
    hass = types.SimpleNamespace(states=states)

    def publisher(hass, entity_id, value, attributes):
        raw = str(value)
        hass.states.writes.append((entity_id, raw, dict(attributes)))
        hass.states.data[entity_id] = types.SimpleNamespace(
            state=raw,
            attributes=dict(attributes),
        )

    installer = _load_manual_hygiene_installer(
        types.SimpleNamespace(EfficientAgileSmartExportManager=RuntimeManager),
        types.SimpleNamespace(ShadowValidationRecorder=Shadow),
        types.SimpleNamespace(KEMSUpdateOrchestrator=Updater),
        publisher,
    )
    installer()
    manager = RuntimeManager()
    manager._hass = hass
    with coalesce_identical_settlement_publications(manager) as counters:
        manager._set("sensor.today", "Ready", {"soc": 75, "rate": 20})
        manager._set("sensor.today", "Ready", {"soc": 75, "rate": 20})
        manager._set("sensor.today", "Ready", {"soc": 74, "rate": 20})
        manager._set("sensor.today", "Ready", {"soc": 74, "rate": 20})
        manager._set("sensor.tomorrow", "Ready", {"rate": 22})
    assert counters.summary()["attempted"] == 5
    assert counters.summary()["compared"] == 3
    assert counters.summary()["skipped_identical"] == 2
    assert counters.summary()["written"] == 3
    assert [x[0] for x in states.writes] == [
        "sensor.today",
        "sensor.today",
        "sensor.tomorrow",
    ]
    assert states.get("sensor.today").attributes["soc"] == 74
    assert manager._kems_settlement_publication_scope is None
    # A new scan does not inherit seen entities; ordinary publication is intact.
    manager._set("sensor.today", "Ready", {"soc": 74, "rate": 20})
    assert len(states.writes) == 4


def test_alpha9162_effective_recorder_coalescer_fails_open_on_lookup_fault() -> None:
    """A bad HA state comparison must not suppress an updated price or SOC."""

    class RuntimeManager:
        def _set(self, entity_id, value, attributes):
            pass

    class Shadow:
        def _set(self, entity_id, value, attributes):
            pass

    class Updater:
        def _write_legacy_states(self):
            pass

    writes = []
    states = types.SimpleNamespace(
        get=lambda entity_id: (_ for _ in ()).throw(
            ValueError("state lookup unavailable")
        )
    )
    hass = types.SimpleNamespace(states=states)

    def publisher(hass, entity_id, value, attributes):
        writes.append((entity_id, value, dict(attributes)))

    installer = _load_manual_hygiene_installer(
        types.SimpleNamespace(EfficientAgileSmartExportManager=RuntimeManager),
        types.SimpleNamespace(ShadowValidationRecorder=Shadow),
        types.SimpleNamespace(KEMSUpdateOrchestrator=Updater),
        publisher,
    )
    installer()
    manager = RuntimeManager()
    manager._hass = hass
    with coalesce_identical_settlement_publications(manager) as counters:
        manager._set("sensor.agile_rate", 20, {"soc": 17})
        manager._set("sensor.agile_rate", 21, {"soc": 16})
    assert counters.summary()["skipped_identical"] == 0
    assert counters.summary()["written"] == 2
    assert len(writes) == 2
