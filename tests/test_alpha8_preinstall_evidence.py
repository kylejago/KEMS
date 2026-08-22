"""Alpha8 contracts for canonical Alpha7.20 pre-install evidence ownership."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
FACADE = KEMS / "agile_preinstall_evidence.py"
EVIDENCE_RUNTIME = KEMS / "agile_preinstall_evidence_runtime.py"
DASHBOARD_RUNTIME = KEMS / "agile_preinstall_dashboard_runtime.py"
HISTORICAL_EVIDENCE = KEMS / "agile_alpha720_preinstall.py"
HISTORICAL_DASHBOARD = KEMS / "agile_alpha720_dashboard.py"
COMPAT = KEMS / "agile_alpha7_compat.py"
HISTORICAL_RUNTIME = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"


def _post_base_specs() -> list[tuple[str, str]]:
    source = COMPAT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "POST_BASE_PATCHES":
            continue
        assert isinstance(node.value, ast.Tuple)
        return [
            (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            for item in node.value.elts
            if isinstance(item, ast.Tuple) and len(item.elts) == 2
        ]
    raise AssertionError("POST_BASE_PATCHES not found")


def test_live_registry_retires_alpha720_and_preserves_install_order() -> None:
    specs = _post_base_specs()
    validation_dashboard = (
        "agile_validation_evidence",
        "install_validation_dashboard",
    )
    preinstall = ("agile_preinstall_evidence", "install_preinstall_evidence")
    dashboard = ("agile_preinstall_evidence", "install_preinstall_dashboard")
    horizon = ("agile_price_horizon_safety", "install_price_horizon_safety")

    assert specs.index(preinstall) > specs.index(validation_dashboard)
    assert specs.index(dashboard) == specs.index(preinstall) + 1
    assert specs.index(dashboard) < specs.index(horizon)
    assert not any(
        module_name in {"agile_alpha720_preinstall", "agile_alpha720_dashboard"}
        for module_name, _ in specs
    )


def test_canonical_alpha720_runtimes_are_byte_identical() -> None:
    assert EVIDENCE_RUNTIME.read_bytes() == HISTORICAL_EVIDENCE.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()


def test_alpha720_facade_needs_no_legacy_module_bridge() -> None:
    source = FACADE.read_text(encoding="utf-8")
    assert "agile_preinstall_evidence_runtime" in source
    assert "agile_preinstall_dashboard_runtime" in source
    assert "install_alpha720_preinstall_patch" in source
    assert "install_alpha720_dashboard_patch" in source
    assert "sys.modules" not in source
    assert "_bind_legacy_name" not in source
    assert "agile_alpha720_" not in source


def test_downstream_frozen_runtimes_do_not_import_alpha720_names() -> None:
    downstream = (
        "agile_price_horizon_safety_runtime.py",
        "agile_shadow_command_runtime.py",
        "agile_outcome_parity_runtime.py",
        "agile_nonzero_export_proof_runtime.py",
        "agile_provisional_planning_runtime.py",
        "agile_price_recovery_runtime.py",
        "agile_bounded_partial_runtime.py",
    )
    for name in downstream:
        source = (KEMS / name).read_text(encoding="utf-8")
        assert "agile_alpha720_preinstall" not in source
        assert "agile_alpha720_dashboard" not in source


def test_preinstall_evidence_remains_hypothetical_and_transparent() -> None:
    source = EVIDENCE_RUNTIME.read_text(encoding="utf-8")
    assert "https://archive-api.open-meteo.com/v1/archive" in source
    assert '"hourly": "global_tilted_irradiance"' in source
    assert '"actual_solar_generation": False' in source
    assert '"comparison_class": "hypothetical_preinstall_evidence"' in source
    assert '"method": "ha_house_load+open_meteo_proposal_solar"' in source
    assert "historical weather reanalysis is not a historical forecast" in source


def test_preinstall_evidence_preserves_priority_cache_and_fail_safe() -> None:
    source = EVIDENCE_RUNTIME.read_text(encoding="utf-8")
    assert "baseline = await original_records(" in source
    assert (
        "backfill._merge_native_and_backfill(baseline, list(evidence_records))"
        in source
    )
    assert '_kems_alpha720_evidence_day", None) != local_day' in source
    assert "network evidence must never break KEMS" in source
    assert "historical irradiance fetch failed" in source
    assert "recorder.get_statistics is unavailable" in source


def test_preinstall_dashboard_preserves_readiness_split() -> None:
    source = DASHBOARD_RUNTIME.read_text(encoding="utf-8")
    assert "Pre-install historical evidence" in source
    assert "Historical proposal-solar reconstruction" in source
    assert "Digital-twin shadow readiness" in source
    assert "Hardware shadow readiness" in source
    assert "Shadow readiness — digital twin vs hardware" in source
    assert "Neither stage sends inverter writes in alpha7.20" in source


def test_alpha720_canonicalisation_introduces_no_hardware_write_path() -> None:
    source = EVIDENCE_RUNTIME.read_text(encoding="utf-8").lower()
    facade = FACADE.read_text(encoding="utf-8").lower()
    forbidden = (
        "foxess_modbus.write",
        'hass.services.async_call("foxess',
        "hass.services.async_call('foxess',",
        "commands_permitted = true",
        "safe_to_write_hardware = true",
    )
    assert not any(value in source for value in forbidden)
    assert not any(value in facade for value in forbidden)
    assert '"real_hardware_writes": "blocked"' in source


def test_historical_alpha720_metadata_and_version_remain_unchanged() -> None:
    historical = HISTORICAL_RUNTIME.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert "install_alpha720_preinstall_patch()" in historical
    assert "install_alpha720_dashboard_patch()" in historical
    assert manifest["version"] == "0.8.0-alpha8.0"


def test_alpha720_ownership_note_is_explicitly_refactor_only() -> None:
    note = (ROOT / "docs/alpha8-preinstall-evidence-canonicalisation.md").read_text(
        encoding="utf-8"
    )
    assert "7242441149ef34bb7e0a31c0de4da3631dadc288" in note
    assert "4abcd4d13f02add98ee4920b87ee3ff302214735" in note
    assert "ownership-only" in note
    assert "real hardware writes remain blocked" in note
