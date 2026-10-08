"""Alpha9.77 pending Intelligent EV-hold regressions."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from kems_core import ControlConfig, ControlState, Snapshot
from kems_core.control_write_authority import (
    assess_foxess_control_write_authority,
    resolve_live_min_soc_on_grid,
    should_freeze_owned_ev_hold,
)
from kems_core.ev_grid_guard import protect_pending_intelligent_ev_hold

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
COORDINATOR = KEMS / "coordinator.py"
BACKEND = KEMS / "foxess_control_backend.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _snapshot(**updates: object) -> Snapshot:
    values: dict[str, object] = {
        "off_peak": False,
        "intelligent_slot": False,
        "intelligent_slot_confirmation": (
            "Intelligent start/end window is unavailable"
        ),
        "intelligent_slot_evidence": {
            "enabled": True,
            "confirmed": False,
            "reason": "Intelligent start/end window is unavailable",
            "octopus_intelligent_slot": True,
            "octopus_price_corroborated": True,
            "ohme_connected": True,
            "ohme_charging": True,
            "ohme_power_active": True,
        },
        "ev_connected": True,
        "ev_charging": True,
        "ev_power_kw": 7.3,
        "ev_power_age_seconds": 5.0,
        "battery_soc": 90.0,
        "battery_power_kw": 7.5,
        "grid_import_kw": 0.8,
        "house_load_kw": 8.1,
        "source_data_age_seconds": 5.0,
        "tariff_source_age_seconds": {"intelligent_slot": 1.0},
        "stale_fields": (),
        "tariff_stale_fields": (),
    }
    values.update(updates)
    return Snapshot(**values)


def _control(**updates: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "control",
        "operating_reason": "awaiting_export_tariff",
        "desired_work_mode": "Self Use",
        "desired_charge_power_kw": 0.0,
        "desired_min_soc_percent": 15.0,
        "desired_grid_export_allowed": False,
        "desired_battery_export_power_kw": 0.0,
        "data_fresh": True,
        "plan_safe": True,
        "grid_available": True,
        "preflight_passed": 15,
        "preflight_total": 15,
    }
    values.update(updates)
    return ControlState(**values)


def _config(**updates: object) -> ControlConfig:
    values: dict[str, object] = {
        "operating_mode": "control",
        "control_enabled": True,
        "commissioned": True,
        "emergency_stop": False,
        "stale_data_seconds": 180,
        "site_import_limit_kw": 14.5,
    }
    values.update(updates)
    return ControlConfig(**values)


def test_pending_window_arms_soc_plus_one_without_cheap_authority() -> None:
    guarded = protect_pending_intelligent_ev_hold(
        _snapshot(),
        _control(),
        _config(),
        no_paid_export_mode=True,
    )

    assert guarded.ev_grid_guard_status == (
        "ev_battery_hold_pending_intelligent_window"
    )
    assert guarded.desired_work_mode == "Self Use"
    assert guarded.desired_charge_power_kw == 0.0
    assert guarded.desired_min_soc_percent == 91.0
    assert guarded.desired_battery_to_home_power_kw == 0.0
    assert guarded.desired_total_discharge_power_kw == 0.0
    assert guarded.total_site_import_kw == 8.3
    assert guarded.site_import_headroom_kw == 6.2


def test_pending_hold_never_becomes_force_charge_authority() -> None:
    guarded = protect_pending_intelligent_ev_hold(
        _snapshot(),
        _control(),
        _config(),
        no_paid_export_mode=True,
    )
    decision = assess_foxess_control_write_authority(
        guarded,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=False,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )

    assert decision.commands_permitted is True
    assert decision.action == "self_use"
    assert decision.force_charge_power_kw is None
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
            pending_intelligent_ev_hold_active=True,
        )
        == 91.0
    )
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
            pending_intelligent_ev_hold_active=False,
        )
        == 10.0
    )


def test_pending_hold_requires_exact_correlated_publication_gap() -> None:
    base = _control()
    config = _config()

    for evidence_update in (
        {"octopus_intelligent_slot": False},
        {"octopus_price_corroborated": False},
        {"ohme_charging": False},
        {"ohme_power_active": False},
        {"reason": "current time is outside the Intelligent window"},
    ):
        evidence = dict(_snapshot().intelligent_slot_evidence)
        evidence.update(evidence_update)
        snap = _snapshot(intelligent_slot_evidence=evidence)
        assert (
            protect_pending_intelligent_ev_hold(
                snap,
                base,
                config,
                no_paid_export_mode=True,
            )
            is base
        )

    assert (
        protect_pending_intelligent_ev_hold(
            _snapshot(tariff_stale_fields=("intelligent_slot",)),
            base,
            config,
            no_paid_export_mode=True,
        )
        is base
    )
    assert (
        protect_pending_intelligent_ev_hold(
            _snapshot(ev_connected=False),
            base,
            config,
            no_paid_export_mode=True,
        )
        is base
    )


def test_pending_hold_respects_site_limit_before_shifting_battery_to_grid() -> None:
    guarded = protect_pending_intelligent_ev_hold(
        _snapshot(grid_import_kw=7.5, battery_power_kw=7.5),
        _control(),
        _config(site_import_limit_kw=14.5),
        no_paid_export_mode=True,
    )
    assert guarded.ev_grid_guard_status == (
        "pending_intelligent_hold_blocked_site_limit"
    )
    assert guarded.desired_min_soc_percent == 15.0


def test_pending_hold_does_not_override_confirmed_or_higher_priority_paths() -> None:
    snap = _snapshot(off_peak=True)
    assert snap.cheap_period_confirmed is True
    base = _control()
    assert (
        protect_pending_intelligent_ev_hold(
            snap,
            base,
            _config(),
            no_paid_export_mode=True,
        )
        is base
    )
    assert (
        protect_pending_intelligent_ev_hold(
            _snapshot(),
            replace(base, operating_reason="happy_hour_reward_hour"),
            _config(),
            no_paid_export_mode=True,
        ).ev_grid_guard_status
        != "ev_battery_hold_pending_intelligent_window"
    )


def _freeze_pending(**updates: object) -> bool:
    values: dict[str, object] = {
        "owned_by_kems": True,
        "latched_min_soc_percent": 91.0,
        "last_applied_action": "self_use",
        "observed_min_soc_on_grid_percent": 91.0,
        "last_verified_min_soc_on_grid_percent": 91.0,
        "cheap_period_confirmed": False,
        "source_uncertainty_grace_active": False,
        "no_paid_export_mode": True,
        "ev_connected": True,
        "operating_mode": "control",
        "master_control_enabled": True,
        "user_commissioned": True,
        "emergency_stop": False,
        "island_mode_active": False,
        "grid_available": True,
        "pending_intelligent_ev_hold_active": True,
    }
    values.update(updates)
    return should_freeze_owned_ev_hold(**values)


def test_pending_freeze_requires_live_physical_readback() -> None:
    assert _freeze_pending() is True
    assert (
        _freeze_pending(
            observed_min_soc_on_grid_percent=None,
            last_verified_min_soc_on_grid_percent=91.0,
        )
        is False
    )
    assert _freeze_pending(observed_min_soc_on_grid_percent=10.0) is False
    assert _freeze_pending(pending_intelligent_ev_hold_active=False) is False


def test_timestamp_entities_join_immediate_refresh_inputs() -> None:
    source = COORDINATOR.read_text(encoding="utf-8")
    watched = source.split(
        "self._critical_refresh_entities = critical_control_refresh_entity_ids(",
        1,
    )[1].split(")", 1)[0]

    assert "entities.next_offpeak_start" in watched
    assert "entities.offpeak_end" in watched
    assert "self.entities.next_offpeak_start" in source
    assert "self.entities.offpeak_end" in source
    assert "_ALPHA975_FOLLOW_UP_REFRESH_SECONDS = 2" in source


def test_backend_has_explicit_pending_hold_authority_not_cheap_authority() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    assert "pending_intelligent_ev_hold_active" in source
    assert '"pending_intelligent_ev_hold"' in source
    assert '"pending_intelligent_ev_hold_only"' in source
    assert "Alpha9.76 pending Intelligent EV MinSOC hold" in source


def test_alpha976_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.83"
    assert reason.startswith("Alpha9.83")
    assert "pending Intelligent" in reason
    assert "SOC+1" in reason
    assert "next_offpeak_start" in reason
    assert "offpeak_end" in reason
    assert "never authorises Force Charge" in reason
    assert "Alpha9.75" in reason
