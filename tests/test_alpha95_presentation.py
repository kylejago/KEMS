"""Alpha9.5 live presentation regression contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from custom_components.kems.alpha95_presentation import (
    _state_with_panel_soc,
    improve_alpha95_dashboard,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"


def test_alpha95_current_day_cards_use_stable_flat_entities() -> None:
    content = improve_alpha95_dashboard(DASHBOARD.read_text(encoding="utf-8"))

    assert "states('sensor.kems_whole_home_observed_cost_today')" in content
    assert "states('sensor.kems_whole_home_simulated_cost_today')" in content
    assert "states('sensor.kems_whole_home_energy_today')" in content
    assert "states('sensor.kems_observed_export_income_today')" in content
    assert "states('sensor.kems_simulated_export_income_today')" in content

    assert (
        "{% set live = p.get('live_data', {}) or {} %}\n"
        "              | Cost | Live Data |"
    ) not in content
    assert (
        "{% set kems = p.get('kems', {}) or {} %}\n" "              | Cost | KEMS |"
    ) not in content
    assert "kems.get('home_energy_kwh')" not in content


def test_alpha95_panel_soc_falls_back_to_virtual_soc() -> None:
    class States:
        @staticmethod
        def get(entity_id: str):
            assert entity_id == "sensor.kems_simulated_battery_state_of_charge"
            return SimpleNamespace(state="76.0")

    manager = SimpleNamespace(_hass=SimpleNamespace(states=States()))
    original = {
        "current_routing_snapshot": {
            "available": True,
            "simulated_soc_percent": None,
            "battery_export_kw": 1.5,
        }
    }

    enriched = _state_with_panel_soc(manager, original)

    assert enriched is not original
    assert (
        enriched["current_routing_snapshot"] is not original["current_routing_snapshot"]
    )
    assert enriched["current_routing_snapshot"]["simulated_soc_percent"] == 76.0
    assert original["current_routing_snapshot"]["simulated_soc_percent"] is None


def test_alpha95_panel_soc_keeps_authoritative_routing_soc_when_present() -> None:
    class States:
        @staticmethod
        def get(_entity_id: str):
            raise AssertionError("fallback must not be queried when routing SOC exists")

    manager = SimpleNamespace(_hass=SimpleNamespace(states=States()))
    state = {"current_routing_snapshot": {"simulated_soc_percent": 42.5}}

    assert _state_with_panel_soc(manager, state) is state


def test_alpha95_installs_before_dashboard_sync_and_restores_panel_flow() -> None:
    setup = (KEMS / "__init__.py").read_text(encoding="utf-8")
    repair = (KEMS / "alpha95_presentation.py").read_text(encoding="utf-8")

    assert "install_alpha95_presentation()" in setup
    assert setup.index("install_alpha95_presentation()") < setup.index(
        "await async_sync_managed_dashboard(hass)"
    )
    assert "install_alpha736_panel_flow_patch()" in repair
    assert "sensor.kems_simulated_battery_state_of_charge" in repair


def test_alpha95_presentation_repair_cannot_write_hardware() -> None:
    source = (KEMS / "alpha95_presentation.py").read_text(encoding="utf-8")

    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
        "ModbusClient",
        "commands_permitted = True",
        "safe_to_write_hardware = True",
    ):
        assert forbidden not in source
