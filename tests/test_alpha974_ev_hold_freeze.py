"""Alpha9.74 transient EV-hold freeze regressions."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core.control_write_authority import should_freeze_owned_ev_hold

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
COORDINATOR = KEMS / "coordinator.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _freeze(**overrides: object) -> bool:
    values: dict[str, object] = {
        "owned_by_kems": True,
        "latched_min_soc_percent": 47.0,
        "last_applied_action": "self_use",
        "observed_min_soc_on_grid_percent": 47.0,
        "last_verified_min_soc_on_grid_percent": 47.0,
        "cheap_period_confirmed": True,
        "source_uncertainty_grace_active": False,
        "no_paid_export_mode": True,
        "ev_connected": True,
        "operating_mode": "control",
        "master_control_enabled": True,
        "user_commissioned": True,
        "emergency_stop": False,
        "island_mode_active": False,
        "grid_available": True,
    }
    values.update(overrides)
    return should_freeze_owned_ev_hold(**values)


def test_transient_readiness_loss_freezes_existing_confirmed_cheap_hold() -> None:
    assert _freeze() is True
    assert _freeze(ev_connected=None) is True


def test_freeze_never_survives_explicit_release_authority() -> None:
    assert _freeze(cheap_period_confirmed=False) is False
    assert _freeze(no_paid_export_mode=False) is False
    assert _freeze(ev_connected=False) is False
    assert _freeze(operating_mode="simulate") is False
    assert _freeze(master_control_enabled=False) is False
    assert _freeze(user_commissioned=False) is False
    assert _freeze(emergency_stop=True) is False
    assert _freeze(island_mode_active=True) is False
    assert _freeze(grid_available=False) is False


def test_freeze_requires_real_owned_self_use_latched_floor() -> None:
    assert _freeze(owned_by_kems=False) is False
    assert _freeze(last_applied_action=None) is False
    assert _freeze(last_applied_action="force_charge") is False
    assert _freeze(latched_min_soc_percent=None) is False
    assert _freeze(latched_min_soc_percent=-1.0) is False
    assert _freeze(latched_min_soc_percent=101.0) is False


def test_backend_freeze_path_has_zero_new_write_authority() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    freeze = source.split("if frozen_ev_hold:", 1)[1].split(
        "elif hold_grace_unverified:", 1
    )[0]

    assert "await self._async_number" not in freeze
    assert "await self._async_select" not in freeze
    assert "services.async_call" not in freeze
    assert '"freeze_ev_hold"' in source
    assert '"ev_hold_frozen_on_transient_loss"' in source


def test_coordinator_keeps_alpha973_fast_refresh_and_supplies_hold_state() -> None:
    source = COORDINATOR.read_text(encoding="utf-8")
    assert "critical_control_refresh_entity_ids" in source
    assert "meaningful_control_state_transition" in source
    assert "ev_hold_state = self._ev_grid_hold.status" in source
    assert (
        'ev_hold_floor_percent=ev_hold_state.get("latched_min_soc_percent")' in source
    )
    assert "ev_connected=snapshot.ev_connected" in source


def test_alpha974_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.79"
    assert reason.startswith("Alpha9.79")
    assert "Alpha9.75" in reason
    assert "transient" in reason.lower()
    assert "confirmed-cheap EV" in reason
    assert "without new writes" in reason
    assert "Active Force Charge is never frozen" in reason
    assert "Alpha9.73 removes the normal coordinator-poll delay" in reason
    assert "10%" in reason
