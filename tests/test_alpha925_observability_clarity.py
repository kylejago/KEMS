"""Alpha9.25 regressions for reserve wording and cheap-window charge observability."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core.tomorrow_soc_handoff import project_cheap_window_charge_capability

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_standard_six_hour_window_reports_100_percent_unreachable_from_10_percent() -> (
    None
):
    evidence = project_cheap_window_charge_capability(
        starting_soc_percent=10.0,
        target_soc_percent=100.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        charge_hours=6.0,
    )

    assert evidence["charge_target_soc_percent"] == 100.0
    assert evidence["charge_hours_available"] == 6.0
    assert evidence["maximum_achievable_soc_percent"] == 80.72
    assert evidence["charge_target_physically_reachable"] is False
    assert evidence["charge_target_shortfall_percent"] == 19.28
    assert evidence["max_charge_kw"] == 7.0
    assert evidence["hardware_writes"] == "blocked"


def test_charge_capability_clamps_at_target_when_window_is_sufficient() -> None:
    evidence = project_cheap_window_charge_capability(
        starting_soc_percent=80.0,
        target_soc_percent=100.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        charge_hours=6.0,
    )

    assert evidence["maximum_achievable_soc_percent"] == 100.0
    assert evidence["charge_target_physically_reachable"] is True
    assert evidence["charge_target_shortfall_percent"] == 0.0


def test_final_publication_clarifies_export_target_and_absolute_floor_labels() -> None:
    source = (KEMS / "agile_observability_clarity.py").read_text(encoding="utf-8")
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    assert "deliberate-export target reached" in source
    assert "absolute" in source
    assert "floor until cheap charge; no deliberate export" in source
    assert "planning target limits deliberate export only" in source
    assert 'slot["actions"] = [action]' in source
    assert 'slot["rolling_action"] = action' in source
    assert 'routing["routing_action"] = action' in source
    assert "install_observability_clarity()" in runtime


def test_alpha925_scope_is_observability_only_and_hardware_blocked() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    clarity = (KEMS / "agile_observability_clarity.py").read_text(encoding="utf-8")
    handoff = (KEMS / "kems_core" / "tomorrow_soc_handoff.py").read_text(
        encoding="utf-8"
    )

    assert manifest["version"] == "0.9.0-alpha9.28"
    reason = str(bundle["maintenance"]["reason"]).lower()
    assert "alpha9.25" in reason
    assert "observability" in reason
    assert "15%" in reason and "10%" in reason and "12%" in reason
    assert "7.0 kw" in reason
    assert '"hardware_writes": "blocked"' in clarity
    assert '"hardware_writes": "blocked"' in handoff
    assert ".services.async_call(" not in clarity
    assert ".services.async_call(" not in handoff
    assert "safe_to_write_hardware = True" not in clarity
    assert "safe_to_write_hardware = True" not in handoff
