"""Alpha9.185 FoxESS Modbus exact-version compatibility and fail-closed contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def _contract():
    path = KEMS / "foxess_modbus_contract.py"
    spec = importlib.util.spec_from_file_location("kems_foxess_185_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("observed_version", "reviewed"),
    [
        ("1.15.0", True),
        ("1.16.0", True),
        ("1.14.0", False),
        ("1.16.1", False),
        ("1.17.0", False),
        ("2.0.0", False),
        (None, False),
        ("", False),
        ("1.16.0-dev", False),
    ],
)
def test_foxess_approval_is_an_exact_two_version_allowlist(observed_version, reviewed):
    contract = _contract()
    assert contract.FOXESS_MODBUS_REVIEWED_VERSIONS == ("1.15.0", "1.16.0")
    assert contract.foxess_modbus_version_is_reviewed(observed_version) is reviewed


def test_contract_diagnostics_expose_both_reviewed_versions():
    contract = _contract()
    snapshot = contract.foxess_modbus_contract_snapshot()
    assert snapshot["reviewed_upstream_version"] == "1.16.0"
    assert snapshot["reviewed_upstream_versions"] == ["1.15.0", "1.16.0"]
    assert snapshot["required_telemetry"]["battery_power_kw"]["key"] == "invbatpower"
    assert snapshot["required_telemetry"]["grid_export_kw"]["key"] == "feed_in"
    assert snapshot["known_writable_capabilities"]["export_power_limit"] == (
        "Export Power Limit (KH_133, W)"
    )
    assert "import-power-limit writes" in snapshot["blocked_live_capabilities"]


def test_backend_reuses_exact_allowlist_but_preserves_all_control_gates():
    source = (KEMS / "foxess_control_backend.py").read_text(encoding="utf-8")
    assert (
        "version_matches = foxess_modbus_version_is_reviewed(observed_version)"
        in source
    )
    assert "reviewed_version_matches=version_matches" in source
    assert "and version_matches" in source
    assert (
        '"reviewed_foxess_modbus_versions": list(FOXESS_MODBUS_REVIEWED_VERSIONS)'
        in source
    )
    assert "_PAID_EXPORT_STAGE_KW = 1.0" in source
    assert "_PAID_EXPORT_PROOF_SAMPLES = 2" in source
    assert "_PAID_EXPORT_FAILURE_SAMPLES = 3" in source
    assert "_commissioning_restore_readback_matches(" in source
    assert "paid_export_stage_ct_conflict(" in source
    assert "not cheap_period_confirmed" in source
    assert "export_tariff_type_from_options" in source
    assert "Import Power Limit is never written." in source


def test_release_metadata_identity_matches_185():
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    reason = json.loads(
        (KEMS.parents[1] / "release/kems-bundle.template.json").read_text(
            encoding="utf-8"
        )
    )["maintenance"]["reason"]
    assert manifest["version"] == "0.9.0-alpha9.196"
    assert reason.startswith("Alpha9.196:")
    assert "FoxESS Modbus 1.15.0 and 1.16.0" in reason
    assert "06:00-06:30" in reason
