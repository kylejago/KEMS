"""Regression coverage for the Alpha8.16 final managed-dashboard pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
PIPELINE_PATH = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"
CONSOLIDATION_PATH = ROOT / "custom_components" / "kems" / "dashboard_consolidation.py"
INIT_PATH = ROOT / "custom_components" / "kems" / "__init__.py"
MANIFEST_PATH = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE_PATH = ROOT / "release" / "kems-bundle.template.json"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PIPELINE = _load_module("kems_dashboard_pipeline_alpha816_test", PIPELINE_PATH)
CONSOLIDATION = _load_module(
    "kems_dashboard_consolidation_alpha816_test", CONSOLIDATION_PATH
)


def _source_dashboard() -> str:
    parts = ["title: KEMS Master Dashboard\n\nviews:\n"]
    for index, title in enumerate(sorted(CONSOLIDATION.EXPECTED_SOURCE_TITLES)):
        path = f"source-{index}"
        parts.append(
            f"  - title: {title}\n"
            f"    path: {path}\n"
            "    cards:\n"
            "      - type: markdown\n"
            "        content: |\n"
            f"          Source evidence for {title}\n"
        )
    return "\n".join(part.rstrip() for part in parts).rstrip() + "\n"


def _top_level_titles(content: str) -> list[str]:
    return [
        line.split(":", 1)[1].strip()
        for line in content.splitlines()
        if line.startswith("  - title: ")
    ]


def test_real_consolidation_runs_before_final_live_data_kems_presentation() -> None:
    """The complete legacy source contract must survive until consolidation."""
    source = _source_dashboard()
    consolidated = CONSOLIDATION.consolidate_dashboard(source)

    assert "  - title: Live Data\n" in consolidated
    assert "  - title: Battery & Solar\n" in consolidated
    assert "  - title: Full KEMS\n" in consolidated
    assert "  - title: Full KEMS Agile\n" in consolidated

    final = PIPELINE.canonicalize_final_dashboard(consolidated)
    titles = _top_level_titles(final)

    assert "Live Data" in titles
    assert "KEMS" in titles
    assert "Battery & Solar" not in titles
    assert "Full KEMS" not in titles
    assert "Full KEMS Agile" not in titles
    assert "Two user-facing products" in final
    assert "perform_action: kems.check_for_updates" in final


def test_update_button_uses_final_system_view_and_is_idempotent() -> None:
    content = (
        "title: KEMS Master Dashboard\n\n"
        "views:\n"
        "  - title: System\n"
        "    path: system\n"
        "    cards:\n"
        "      - type: markdown\n"
        "        content: System health\n"
    )

    once = PIPELINE.inject_update_button(content)
    twice = PIPELINE.inject_update_button(once)

    assert once == twice
    assert once.count("perform_action: kems.check_for_updates") == 1
    assert once.index("perform_action: kems.check_for_updates") < once.index(
        "content: System health"
    )


def test_pipeline_restores_readability_then_finalizes_the_complete_builder() -> None:
    content = PIPELINE_PATH.read_text(encoding="utf-8")
    init = INIT_PATH.read_text(encoding="utf-8")

    assert (
        "dashboard._dashboard_readability_pass = baseline_readability_pass" in content
    )
    assert 'content = original_builder().decode("utf-8")' in content
    assert "content = improve_energy_bill_dashboard(content)" in content
    assert "content = canonicalize_final_dashboard(content)" in content
    assert "convergent._managed_dashboard_bytes = managed_dashboard_bytes" in content
    assert (
        init.index("install_energy_bill_dashboard_patch()")
        < init.index("install_dashboard_pipeline()")
        < init.index("await async_sync_managed_dashboard(hass)")
    )


def test_alpha816_release_scope_keeps_web_panel_and_hardware_boundary_unchanged() -> (
    None
):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    content = PIPELINE_PATH.read_text(encoding="utf-8")

    assert manifest["version"].startswith("0.8.0-alpha8.")
    assert int(manifest["version"].rsplit(".", 1)[-1]) >= 16
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "real_backend" not in content
    assert "commands_permitted" not in content