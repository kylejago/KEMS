"""Alpha9.50 final managed-dashboard event-card preservation contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MASTER = KEMS / "kems_master_dashboard.yaml"
PIPELINE = KEMS / "dashboard_pipeline.py"
CONTRACT = KEMS / "alpha937_dashboard_contract.py"
CARD = KEMS / "power_down_dashboard_card.yaml"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_dashboard() -> tuple[object, bytes]:
    # Mirror the installed runtime order: finalise first, then apply the
    # authoritative Alpha9.37+ customer reporting contract.
    pipeline = _module(PIPELINE, "alpha950_dashboard_pipeline")
    contract = _module(CONTRACT, "alpha950_dashboard_contract")
    base = pipeline._finalise_dashboard_bytes(MASTER.read_bytes())
    return contract, contract.repair_dashboard_contract(base)


def _kems_view(payload: bytes) -> str:
    text = payload.decode()
    return text.split("\n  - title: KEMS\n", 1)[1].split("\n  - title: Compare\n", 1)[0]


def test_alpha950_runtime_pipeline_keeps_both_event_cards_in_order() -> None:
    contract, payload = _runtime_dashboard()
    kems = _kems_view(payload)

    energy = kems.index("        title: Energy today\n")
    happy = kems.index("        title: Weekend Happy Hour\n")
    power_down = kems.index("        title: Power Down\n")
    history = kems.index("        title: Power history — today\n")

    assert energy < happy < power_down < history
    assert kems.count("        title: Weekend Happy Hour\n") == 1
    assert kems.count("        title: Power Down\n") == 1
    assert "saving_session_joined" in kems
    assert "estimated_saving_session_total_income_pence" in kems
    assert CARD.read_text(encoding="utf-8").strip() in kems

    # The final reporting contract is deliberately idempotent so updater
    # verification and startup sync cannot duplicate either event card.
    assert contract.repair_dashboard_contract(payload) == payload


def test_alpha950_contract_narrows_kems_parity_before_happy_hour() -> None:
    source = CONTRACT.read_text(encoding="utf-8")

    assert "_KEMS_HAPPY_HOUR_MARKER" in source
    assert "_KEMS_POWER_HISTORY_MARKER" in source
    assert "def _repair_kems_event_cards(content: str) -> str:" in source
    assert "POWER_DOWN_CARD_PATH.read_text" in source
    assert "content = _repair_kems_event_cards(content)" in source


def test_alpha950_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.63"
    assert reason.startswith("Alpha9.63")
    assert "Weekend Happy Hour" in reason
    assert "Power Down" in reason
    assert "final managed dashboard" in reason
    assert "presentation" in reason
    assert "FoxESS hardware-write authority" in reason
