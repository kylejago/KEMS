"""Alpha9.49 permanent Power Down dashboard observability contract."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
DASHBOARD = KEMS / "dashboard.py"
CARD = KEMS / "power_down_dashboard_card.yaml"
SENSORS = KEMS / "sensor.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


POWER_DOWN_ATTRIBUTES = (
    "saving_session_active",
    "saving_session_joined",
    "saving_session_start",
    "saving_session_end",
    "saving_session_duration_minutes",
    "saving_session_octopoints_per_kwh",
    "saving_session_bonus_rate_pence",
    "saving_session_baseline_net_kwh",
    "saving_session_baseline_source",
    "saving_session_baseline_incomplete",
    "saving_session_battery_reserve_kwh",
    "saving_session_export_target_kw",
    "estimated_saving_session_export_kwh",
    "estimated_saving_session_rewardable_reduction_kwh",
    "estimated_saving_session_bonus_pence",
    "estimated_saving_session_export_income_pence",
    "estimated_saving_session_total_income_pence",
    "battery_reserved_for_saving_session",
    "battery_export_reduced_for_saving_session",
)


def test_alpha949_power_down_card_surfaces_existing_session_evidence() -> None:
    card = CARD.read_text(encoding="utf-8")
    sensors = SENSORS.read_text(encoding="utf-8")

    assert "title: Power Down" in card
    for attribute in POWER_DOWN_ATTRIBUTES:
        assert attribute in card
        assert f'"{attribute}"' in sensors

    assert "Simulation/read-only" in card
    assert "does not join sessions" in card
    assert "write FoxESS hardware" in card
    assert ".services.async_call(" not in card
    assert "service:" not in card
    assert "action:" not in card


def test_alpha949_managed_dashboard_injects_card_after_happy_hour() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")

    assert "PACKAGED_POWER_DOWN_CARD_PATH = Path(__file__).with_name(" in source
    assert '"power_down_dashboard_card.yaml"' in source
    assert "def _inject_power_down_card(content: str) -> str:" in source
    assert 'if "        title: Power Down\\n" in content:' in source
    assert "This is KEMS planning/booking evidence" in source
    assert '"        title: Power history — today"' in source
    assert "Managed KEMS dashboard has no Power Down insertion anchor" in source
    assert "master = _inject_power_down_card(master)" in source


def test_alpha949_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.55"
    assert reason.startswith("Alpha9.55")
    assert "Power Down" in reason
    assert "dashboard/observability" in reason
    assert "joining" in reason
    assert "FoxESS hardware-write authority" in reason
    assert "real hardware writes remain hard-blocked" in reason
