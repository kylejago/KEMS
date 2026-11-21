"""Alpha9.248: timestamps are not independent proof of physical sampling."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SOURCE = (
    Path(__file__).parents[1]
    / "custom_components"
    / "kems"
    / "kems_core"
    / "diagnostic_evidence.py"
)
spec = importlib.util.spec_from_file_location("kems_provenance_alpha9248_test", SOURCE)
assert spec is not None and spec.loader is not None
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


def test_recent_raw_report_does_not_certify_independent_physical_remeasurement() -> None:
    result = provenance.corroborated_unchanged_sources(
        {"grid_ct": 5.0, "battery": 180.0, "missing": None},
        ("battery",),
        90,
    )
    fields = result["raw_report_provenance"]["fields"]
    assert fields["grid_ct"]["status"] == "raw_timestamp_within_limit"
    assert fields["grid_ct"]["raw_report_within_freshness_limit"] is True
    assert fields["grid_ct"]["physical_remeasurement_proven"] is False

    assert fields["battery"]["status"] == "rejected_as_stale"
    assert fields["battery"]["raw_report_within_freshness_limit"] is False
    assert fields["battery"]["physical_remeasurement_proven"] is False

    assert fields["missing"]["status"] == "raw_timestamp_missing"
    assert fields["missing"]["physical_remeasurement_proven"] is False
    assert result["raw_report_provenance"][
        "changes_control_freshness_or_foxess_commands"
    ] is False


def test_cohort_accepted_unchanged_is_not_a_physical_remeasurement() -> None:
    result = provenance.corroborated_unchanged_sources(
        {"pv": 182.0}, (), 90
    )
    data = result["raw_report_provenance"]["fields"]["pv"]
    assert data["status"] == "accepted_unchanged_by_device_cohort_not_remeasured"
    assert data["raw_report_within_freshness_limit"] is False
    assert data["physical_remeasurement_proven"] is False
