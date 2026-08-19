"""Regression coverage for alpha7.27 Agile price recovery observability."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha727_price_recovery.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-price-recovery-observability.md"


def test_alpha727_manifest_is_exact() -> None:
    assert '"version": "0.7.0-alpha7.27"' in MANIFEST.read_text(encoding="utf-8")


def test_alpha727_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha727_installs_after_alpha726() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha727_price_recovery_patch" in loader
    assert loader.rindex("install_alpha727_price_recovery_patch()") > loader.rindex(
        "install_alpha726_provisional_planning_patch()"
    )


def test_alpha727_bypasses_double_alpha726_retry() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha726.alpha726_original_fetch_rates(self, records, now)" in source
    assert "_fetch_rates_with_observable_recovery" in source
    assert '"_kems_alpha727_price_recovery"' in source


def test_alpha727_embeds_retry_evidence_in_agile_state() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'state["price_fetch_diagnostics"] = diagnostics' in source
    assert 'state["price_fetch_status"] = diagnostics.get("recovery_outcome")' in source
    assert "sensor.kems_agile_price_fetch_diagnostics" in source
    assert '"attempts": []' in source
    assert '"targeted_retry_attempt_count": 0' in source


def test_alpha727_records_exact_local_and_utc_request_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    for field in (
        '"period_from_utc"',
        '"period_to_utc"',
        '"period_from_local"',
        '"period_to_local"',
        '"http_status"',
        '"result_count"',
        '"matching_result_count"',
        '"returned_intervals"',
        '"error_type"',
        '"error"',
    ):
        assert field in source


def test_alpha727_uses_context_window_only_as_recovery_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "CONTEXT_PADDING = timedelta(minutes=30)" in source
    assert 'request_kind="exact_half_hour"' in source
    assert 'request_kind="context_window"' in source
    assert "_matching_results(context_results, start, end)" in source
    assert "recovered_rates.append(_agile_rate_from_result(self, item))" in source
    assert "if context_matches:" in source
    assert "octopus_slot_not_published" in source
    assert "octopus_no_results" in source


def test_alpha727_distinguishes_upstream_gap_from_retrieval_failure() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"recovered_exact"' in source
    assert '"recovered_context"' in source
    assert '"octopus_missing_price"' in source
    assert '"retrieval_error"' in source
    assert '"primary_fetch_error"' in source
    assert "KEMS could not complete one or more recovery requests" in source
    assert (
        "Octopus responded successfully but did not publish the target slot" in source
    )


def test_alpha727_retains_alpha726_diagnostic_compatibility() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "self._kems_alpha727_price_fetch_diagnostics = diagnostics" in source
    assert "self._kems_alpha726_rate_fetch_diagnostics = diagnostics" in source
    assert "missing_slots_for_day" in source
    assert "expected_slots_for_day" in source


def test_alpha727_remains_hardware_write_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"hardware_writes": "blocked"' in source
    assert "never permits FoxESS hardware writes" in source


def test_alpha727_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.27" in source
    assert "exact half-hour" in source
    assert "context window" in source
    assert "Octopus" in source
    assert "retrieval error" in source
    assert "never invents" in source
    assert "Real FoxESS hardware writes remain blocked" in source
