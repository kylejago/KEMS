"""Alpha9.246: operator display, physical solar parity and EV cap audit.

These tests intentionally exercise read-only projections independently of HA
startup. The original commissioning snapshot and physical write gates remain
unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _commissioning_operator_state():
    source = (KEMS / "commissioning.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    fn = next(
        n
        for n in module.body
        if isinstance(n, ast.FunctionDef)
        and n.name == "commissioning_operator_state"
    )
    result = {}
    exec(
        compile(ast.Module(body=[fn], type_ignores=[]), "<commissioning>", "exec"),
        {"Mapping": Mapping, "Any": Any},
        result,
    )
    return result["commissioning_operator_state"]


def test_display_reconciles_verified_live_control_after_snapshot_race():
    display = _commissioning_operator_state()
    control = SimpleNamespace(
        commissioned=True, commands_permitted=True, preflight_status="PASS"
    )
    assert (
        display({"state": "Ready for Shadow", "ready_for_control": True}, None)
        == "Ready for Control"
    )
    assert (
        display({"state": "Ready for Shadow", "ready_for_control": False}, control)
        == "Ready for Control"
    )


def test_display_never_promotes_failed_or_uncommissioned_state():
    display = _commissioning_operator_state()
    live = SimpleNamespace(
        commissioned=True, commands_permitted=True, preflight_status="PASS"
    )
    for state in ("Commissioning Failed", "Waiting for Source", "Not Ready"):
        assert display({"state": state, "ready_for_control": False}, live) == state
    for reason in ("commissioned", "commands_permitted", "preflight_status"):
        attrs = dict(
            commissioned=True, commands_permitted=True, preflight_status="PASS"
        )
        attrs[reason] = "WAIT" if reason == "preflight_status" else False
        control = SimpleNamespace(**attrs)
        assert (
            display({"state": "Ready for Shadow", "ready_for_control": False}, control)
            == "Ready for Shadow"
        )


def test_bundle_does_not_modify_existing_physical_write_gates():
    commissioning = (KEMS / "commissioning.py").read_text()
    coordinator = (KEMS / "coordinator.py").read_text()
    trace = (KEMS / "ev_charge_trace.py").read_text()
    solar = (KEMS / "solar_routing_shadow.py").read_text()
    assert 'state == "Ready for Shadow"' in commissioning
    assert '"ready_for_control": ready_for_control' in commissioning
    assert 'commissioning.get("ready_for_control")' in coordinator
    assert 'planned_control=control,' in coordinator
    assert 'solar_shadow = evaluate_solar_routing_shadow(' in coordinator
    assert 'solar_shadow["pilot_readiness"]' in coordinator
    assert '"hardware_writes": "forbidden"' in solar
    assert '"new_ev_routing_hardware_authorised": False' in trace
    for forbidden in ("async_call(", "number.set_value", "select.select_option"):
        assert forbidden not in trace
