"""Alpha9.81 restart-safe non-cheap MinSOC baseline regressions."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core.control_write_authority import (
    FoxESSControlDecision,
    repair_contaminated_min_soc_baseline,
    resolve_live_min_soc_on_grid,
)

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_physically_verified_temporary_hold_cannot_remain_the_baseline() -> None:
    repaired = repair_contaminated_min_soc_baseline(
        89.0,
        observed_min_soc_on_grid=89.0,
        last_verified_min_soc_on_grid=89.0,
        minimum_min_soc_on_grid=10.0,
        requested_noncheap_min_soc=15.0,
    )
    assert repaired == 10.0

    decision = FoxESSControlDecision(
        backend_available=True,
        commands_permitted=True,
        action="self_use",
        reason="normal non-cheap control",
        min_soc_on_grid_percent=15.0,
    )
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=repaired,
        )
        == 10.0
    )


def test_baseline_repair_requires_specific_ev_hold_contamination_evidence() -> None:
    common = {
        "observed_min_soc_on_grid": 89.0,
        "last_verified_min_soc_on_grid": 89.0,
        "minimum_min_soc_on_grid": 10.0,
        "requested_noncheap_min_soc": 15.0,
    }
    assert repair_contaminated_min_soc_baseline(10.0, **common) == 10.0
    assert (
        repair_contaminated_min_soc_baseline(
            89.0,
            **{**common, "last_verified_min_soc_on_grid": None},
        )
        == 89.0
    )
    assert (
        repair_contaminated_min_soc_baseline(
            89.0,
            **{**common, "observed_min_soc_on_grid": 10.0},
        )
        == 89.0
    )
    assert (
        repair_contaminated_min_soc_baseline(
            15.0,
            observed_min_soc_on_grid=15.0,
            last_verified_min_soc_on_grid=15.0,
            minimum_min_soc_on_grid=10.0,
            requested_noncheap_min_soc=15.0,
        )
        == 15.0
    )


def test_restore_keeps_ownership_until_work_mode_and_minsoc_read_back() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    restore = source.split("async def _async_restore(\n", 1)[1].split(
        "async def async_shutdown", 1
    )[0]

    assert "mode_verified = bool(" in restore
    assert "soc_verified = bool(" in restore
    assert (
        "paid_settings_ok = await self._async_restore_paid_export_settings(" in restore
    )
    assert (
        "if mode_ok and soc_ok and mode_verified and soc_verified and paid_settings_ok:"
        in restore
    )
    assert "self._owned = False" in restore
    assert "awaiting verified work mode, " in restore
    assert '"MinSOC or paid-export setting readback"' in restore


def test_live_repair_is_blocked_until_every_temporary_hold_path_has_ended() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    update = source.split("async def async_update", 1)[1]
    repair = update.split(
        "repaired_baseline = repair_contaminated_min_soc_baseline", 1
    )[0]

    assert "not cheap_period_confirmed" in repair
    assert "ev_hold_floor_percent is None" in repair
    assert "not ev_hold_source_grace_active" in repair
    assert "not pending_intelligent_ev_hold_active" in repair
    assert "no_paid_export_mode" in repair


def test_alpha981_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.82"
    assert reason.startswith("Alpha9.82")
    assert "4–5 October" in reason
    assert "10%" in reason
    assert "read back" in reason
    assert "Alpha9.75" in reason
    assert "Alpha9.76" in reason
    assert "Alpha9.77" in reason
    assert "No new FoxESS command surface" in reason
    assert "Alpha9.80" in reason
