"""Alpha9.64 fast FoxESS grid-trim regressions."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core.fast_grid_trim import (
    FAST_GRID_TRIM_DEADBAND_W,
    FAST_GRID_TRIM_ENVELOPE_KW,
    FAST_GRID_TRIM_MAX_STEP_KW,
    FAST_GRID_TRIM_POLL_SECONDS,
    calculate_fast_grid_trim,
)

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _result(
    *,
    current: float,
    observed_w: float,
    target_w: float = -10.0,
    base: float = 1.231,
):
    return calculate_fast_grid_trim(
        current_force_discharge_kw=current,
        observed_grid_w=observed_w,
        target_grid_w=target_w,
        planner_base_output_kw=base,
        inverter_limit_kw=7.0,
        max_discharge_kw=7.0,
        planner_discharge_kw=0.0,
        export_limit_kw=6.4,
    )


def test_live_capture_36w_export_reduces_1280_to_1254() -> None:
    result = _result(current=1.280, observed_w=-36.0)

    assert result.error_w == -26.0
    assert result.delta_kw == -0.026
    assert result.target_force_discharge_kw == 1.254
    assert result.changed is True


def test_live_capture_39w_import_raises_base_by_49w() -> None:
    result = _result(current=1.231, observed_w=39.0)

    assert result.error_w == 49.0
    assert result.delta_kw == 0.049
    assert result.target_force_discharge_kw == 1.280


def test_large_error_is_limited_to_50w_per_fresh_sample() -> None:
    upward = _result(current=1.231, observed_w=500.0)
    downward = _result(current=1.280, observed_w=-500.0)

    assert upward.delta_kw == FAST_GRID_TRIM_MAX_STEP_KW
    assert downward.delta_kw == -FAST_GRID_TRIM_MAX_STEP_KW


def test_fast_trim_stays_inside_100w_planner_envelope() -> None:
    high = _result(current=1.320, observed_w=500.0)
    low = _result(current=1.150, observed_w=-500.0)

    assert FAST_GRID_TRIM_ENVELOPE_KW == 0.100
    assert high.envelope_max_kw == 1.331
    assert high.target_force_discharge_kw == 1.331
    assert low.envelope_min_kw == 1.131
    assert low.target_force_discharge_kw == 1.131


def test_5w_deadband_does_not_chase_single_watts() -> None:
    result = _result(current=1.254, observed_w=-7.0)

    assert FAST_GRID_TRIM_DEADBAND_W == 5.0
    assert result.error_w == 3.0
    assert result.target_force_discharge_kw == 1.254
    assert result.changed is False
    assert result.reason == "inside_5w_deadband"


def test_fast_loop_cadence_is_five_seconds_but_fresh_sample_gated() -> None:
    assert FAST_GRID_TRIM_POLL_SECONDS == 5
    source = BACKEND.read_text(encoding="utf-8")
    assert "_fast_trim_last_sample_fingerprint" in source
    assert "duplicate_grid_sample" in source


def test_fast_loop_never_writes_work_mode_or_export_limit() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    fast = source.split("async def _async_fast_grid_trim_once", 1)[1].split(
        "async def async_update", 1
    )[0]

    assert "_async_number(" in fast
    assert "force_discharge_entity" in fast
    assert "_async_select(" not in fast
    assert "export_power_limit" not in fast


def test_alpha964_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.64"
    assert reason.startswith("Alpha9.64 adds a fast FoxESS grid-trim loop")
    assert "60-second planner remains authoritative" in reason
    assert "5-second scheduler" in reason
    assert "fresh FoxESS grid telemetry sample" in reason
    assert "50 W per fresh sample" in reason
    assert "+/-100 W" in reason
    assert "Export Power Limit writes remain blocked" in reason
