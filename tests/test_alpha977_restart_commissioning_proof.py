"""Alpha9.77 restart-safe commissioning proof regressions."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.kems.commissioning_restart_proof import restart_proof_matches

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COORDINATOR = KEMS / "coordinator.py"
COMMISSIONING = KEMS / "commissioning.py"
SESSION = KEMS / "commissioning_session.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


SOURCE = (
    ("battery_power_kw", "sensor.kh7_invbatpower|kW"),
    ("battery_soc", "sensor.kh7_battery_soc|%"),
)
DIRECTION = SOURCE + (
    ("battery_charge_today_kwh", "sensor.kh7_battery_charge_today|kWh"),
    ("battery_discharge_today_kwh", "sensor.kh7_battery_discharge_today|kWh"),
)
PROOF = {
    "certificate_version": 1,
    "source_signature": [
        {"role": role, "identity": identity} for role, identity in SOURCE
    ],
    "direction_source_signature": [
        {"role": role, "identity": identity} for role, identity in DIRECTION
    ],
    "configured_positive_is_discharge": True,
}


def test_restart_proof_requires_exact_identity_and_sign_contract() -> None:
    assert restart_proof_matches(
        PROOF,
        source_signature=SOURCE,
        direction_source_signature=DIRECTION,
        configured_positive_is_discharge=True,
    )
    assert not restart_proof_matches(
        PROOF,
        source_signature=(
            ("battery_power_kw", "sensor.other_battery_power|kW"),
            SOURCE[1],
        ),
        direction_source_signature=DIRECTION,
        configured_positive_is_discharge=True,
    )
    assert not restart_proof_matches(
        PROOF,
        source_signature=SOURCE,
        direction_source_signature=DIRECTION,
        configured_positive_is_discharge=False,
    )
    incomplete_proof = dict(PROOF)
    incomplete_proof.pop("configured_positive_is_discharge")
    assert not restart_proof_matches(
        incomplete_proof,
        source_signature=SOURCE,
        direction_source_signature=DIRECTION,
        configured_positive_is_discharge=False,
    )


def test_restart_bridge_is_wait_only_and_fresh_proof_is_independent() -> None:
    source = COMMISSIONING.read_text(encoding="utf-8")

    assert 'check["status"] != WAIT' in source
    assert 'check["status"] = PASS' in source
    assert "fresh_foxess_telemetry_proof_ready" in source
    assert "restart_live_evidence_consistent" in source
    assert "minimum_samples=1" in source
    assert "restart_commissioning_bridge_active" in source
    assert "restart_proof_matches(" in source


def test_raw_commissioning_samples_remain_session_scoped() -> None:
    source = SESSION.read_text(encoding="utf-8")
    assert "metadata = {" in source
    assert '"persistent": False' in source
    assert "Raw samples remain session-scoped" in source


def test_restart_certificate_loads_before_first_refresh_and_captures_fresh_proof() -> (
    None
):
    source = COORDINATOR.read_text(encoding="utf-8")
    setup = source.split("async def _async_setup", 1)[1].split(
        "async def _async_update_data", 1
    )[0]
    update = source.split("async def _async_update_data", 1)[1]

    assert "await self._commissioning_restart_proof.async_load()" in setup
    assert (
        "await self._commissioning_restart_proof.async_capture(commissioning)" in update
    )


def test_alpha977_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.83"
    assert reason.startswith("Alpha9.83")
    assert "restart commissioning gap" in reason
    assert "WAIT" in reason
    assert "never converts FAIL to PASS" in reason
    assert "does not broaden FoxESS write authority" in reason
