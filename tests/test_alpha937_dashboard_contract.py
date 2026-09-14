"""Alpha9.37 customer-dashboard contract regression tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "custom_components" / "kems" / "alpha937_dashboard_contract.py"


def _module():
    spec = importlib.util.spec_from_file_location("alpha937_dashboard_contract", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_payload() -> bytes:
    return b"""title: KEMS
views:
  - title: Live Data
    path: live-data
    cards:
      - type: entities
        title: Energy today
        entities:
          - entity: sensor.kems_solar_generation_today
      - type: markdown
        title: Power history â        title: Power history \xe2        title: Power history \xe2\x80        title: Power history \xe2\x80\x94 today
        content: keep

  - title: Compare
    path: compare
    cards:
          - type: markdown
            title: KEMS
            content: |
              legacy sensor.kems_compare_full_kems_cost_today
      - type: markdown
        title: Today â        title: Today \xe2        title: Today \xe2\x80        title: Today \xe2\x80\x94 side by side
        content: |
          legacy sensor.kems_compare_full_kems_cost_today
      - type: history-graph
        title: Electricity cost â        title: Electricity cost \xe2        title: Electricity cost \xe2\x80        title: Electricity cost \xe2\x80\x94 Live vs KEMS
        entities: []

  - title: History
    cards:
      - entity: sensor.kems_lifetime_gas_usage
      - entity: sensor.kems_lifetime_total_energy_cost

  - title: ROI
    cards:
      - entity: sensor.kems_financial_house_consumption
      - entity: sensor.kems_financial_solar_generation
      - entity: sensor.kems_financial_grid_import
      - entity: sensor.kems_financial_grid_export
      - entity: sensor.kems_financial_export_income
"""


def test_alpha937_removes_every_observed_stale_dashboard_entity_reference() -> None:
    module = _module()
    repaired = module.repair_dashboard_contract(_legacy_payload()).decode("utf-8")

    for stale in (
        "sensor.kems_solar_generation_today",
        "sensor.kems_lifetime_gas_usage",
        "sensor.kems_lifetime_total_energy_cost",
        "sensor.kems_financial_house_consumption",
        "sensor.kems_financial_solar_generation",
        "sensor.kems_financial_grid_import",
        "sensor.kems_financial_grid_export",
        "sensor.kems_financial_export_income",
    ):
        assert stale not in repaired

    for registered in (
        "sensor.kems_lifetime_gas_consumption",
        "sensor.kems_lifetime_net_energy_cost",
        "sensor.kems_house_consumption_since_commissioning",
        "sensor.kems_solar_generation_since_commissioning",
        "sensor.kems_grid_import_since_commissioning",
        "sensor.kems_grid_export_since_commissioning",
        "sensor.kems_paid_export_income_since_commissioning",
    ):
        assert registered in repaired

    assert "actual_solar_generation_kwh" in repaired


def test_compare_kems_uses_same_canonical_today_entities_as_kems_page() -> None:
    module = _module()
    repaired = module.repair_dashboard_contract(_legacy_payload()).decode("utf-8")
    compare = repaired.split("\n  - title: Compare\n", 1)[1].split(
        "\n  - title: History\n", 1
    )[0]

    assert "sensor.kems_compare_full_kems_cost_today" not in compare
    assert "sensor.kems_whole_home_simulated_cost_today" in compare
    assert "sensor.kems_simulated_grid_import_today" in compare
    assert "sensor.kems_simulated_grid_export_today" in compare
    assert "canonical current-day simulation" in compare


def test_dashboard_contract_repair_is_idempotent_and_reporting_only() -> None:
    module = _module()
    once = module.repair_dashboard_contract(_legacy_payload())
    twice = module.repair_dashboard_contract(once)
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert twice == once
    assert "presentation-only" in source
    assert "control eligibility" not in source
    assert "FoxESS" not in source
