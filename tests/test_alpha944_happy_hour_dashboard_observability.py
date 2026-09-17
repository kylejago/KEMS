# Alpha9.44 managed-dashboard Weekend Happy Hour observability contract.

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def _dashboard() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_alpha944_kems_surfaces_happy_hour_without_live_data_pollution() -> None:
    content = _dashboard()
    live = content.split("\n  - title: Live Data\n", 1)[1].split(
        "\n  - title: KEMS\n", 1
    )[0]
    kems = content.split("\n  - title: KEMS\n", 1)[1].split(
        "\n  - title: Compare\n", 1
    )[0]
    assert "title: Weekend Happy Hour" in kems
    assert "switch.kems_weekend_happy_hour_auto_join" in kems
    for item in (
        "recommended_start",
        "recommended_end",
        "candidate_count",
        "import_price_coverage_percent",
        "export_price_coverage_percent",
        "estimated_free_import_kwh",
        "planned_pre_event_export_kwh",
        "estimated_net_benefit_pence",
        "expected_battery_free_import_kwh",
        "current_reward_hour_import_kwh",
    ):
        assert item in kems
    assert "Simulation/read-only - KEMS will not book." in kems
    assert "Booked - preparing" in kems
    assert "Active" in kems
    assert "Completed" in kems
    assert "switch.kems_weekend_happy_hour_auto_join" not in live
    assert "Weekend Happy Hour" not in live


def test_alpha944_system_exposes_auto_join_economics_and_safety() -> None:
    system = _dashboard().split("\n  - title: System\n", 1)[1]
    assert "Auto join recommended Happy Hour" in system
    assert "title: Happy Hour planner & policy" in system
    assert "join_block_reason" in system
    assert "evaluated_candidates" in system
    assert "expected_house_free_import_kwh" in system
    assert "expected_solar_opportunity_kwh" in system
    assert "external_join_authority" in system
    assert "16 kWh per reward hour" in system
    assert "Ohme control is opt-in" in system


def test_alpha944_dashboard_is_packaged_identically() -> None:
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()


def test_alpha944_release_identity_and_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    reason = str(bundle["maintenance"]["reason"])
    version = str(manifest["version"])
    prefix = "0.9.0-alpha9."
    assert version.startswith(prefix)
    assert int(version.removeprefix(prefix)) >= 48
    assert "Alpha9.44" in reason
    assert "dashboard/observability only" in reason
    assert "Happy Hour scoring or joining logic" in reason
    assert "FoxESS hardware-write authority" in reason
