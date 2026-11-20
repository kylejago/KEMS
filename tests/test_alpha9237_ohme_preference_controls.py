"""Regression for alpha9.237's non-authoritative Ohme preference controls."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

KEMS = Path(__file__).resolve().parents[1] / "custom_components" / "kems"


def _load_policy() -> ModuleType:
    package = ModuleType("kems_alpha9237")
    package.__path__ = [str(KEMS)]
    sys.modules[package.__name__] = package
    name = f"{package.__name__}.ohme_extra_slot_policy"
    spec = importlib.util.spec_from_file_location(
        name, KEMS / "ohme_extra_slot_policy.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sample(**overrides):
    values = {
        "charge_mode": "Smart charge",
        "charger_status": "charging",
        "charging_power_kw": 3.026,
        "regular_offpeak_state": "off",
        "mode_age_seconds": 25.0,
        "status_age_seconds": 25.0,
        "power_age_seconds": 10.0,
    }
    values.update(overrides)
    return values


def test_default_is_manual_savings_on_and_supplier_unconfirmed() -> None:
    policy = _load_policy()
    result = policy.ohme_extra_slot_evidence({}, **_sample())
    assert result["prioritise_savings_declared"] is True
    assert result["declared_extra_slot_tariff"] == "unconfirmed"
    assert result["likely_managed_daytime_charge_candidate"] is True
    assert result["extra_daytime_grid_force_charge_authorised"] is False
    assert result["supplier_discount_confirmed"] is False


def test_whole_home_selection_is_not_a_live_force_charge_authorisation() -> None:
    policy = _load_policy()
    result = policy.ohme_extra_slot_evidence(
        {"ohme_extra_slot_tariff_treatment": "whole_home"}, **_sample()
    )
    assert result["declared_extra_slot_tariff"] == "whole_home"
    assert result["extra_daytime_grid_force_charge_authorised"] is False
    assert result["whole_home_discount_verified"] is False


def test_unknown_stale_overnight_and_manual_off_fail_closed() -> None:
    policy = _load_policy()
    for change in (
        {"charge_mode": "Max charge"},
        {"charge_mode": "unavailable"},
        {"charger_status": "plugged_in"},
        {"charging_power_kw": 0.0},
        {"mode_age_seconds": 250},
        {"regular_offpeak_state": "on"},
        {"regular_offpeak_state": None},
    ):
        assert not policy.ohme_extra_slot_evidence({}, **_sample(**change))[
            "likely_managed_daytime_charge_candidate"
        ]
    assert not policy.ohme_extra_slot_evidence(
        {"ohme_prioritise_savings_confirmed": False}, **_sample()
    )["likely_managed_daytime_charge_candidate"]


def test_options_can_change_without_reloading_commissioned_control() -> None:
    source = (KEMS / "runtime_options.py").read_text(encoding="utf-8")
    definition = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "async_set_ohme_preference_option"
    )
    attrs = [
        node.attr for node in ast.walk(definition) if isinstance(node, ast.Attribute)
    ]
    assert "async_update_entry" in attrs
    assert "async_reload" not in attrs
    switch = (KEMS / "switch.py").read_text(encoding="utf-8")
    select = (KEMS / "select.py").read_text(encoding="utf-8")
    diagnostics = (KEMS / "diagnostics.py").read_text(encoding="utf-8")
    assert "KEMSOHMEPrioritiseSavingsSwitch(coordinator)" in switch
    assert "KEMSOHMEExtraSlotTariffSelect(coordinator)" in select
    assert '"ohme_extra_slot_policy": extra_slot_policy' in diagnostics
    assert '"extra_daytime_grid_force_charge_authorised": False' in diagnostics
