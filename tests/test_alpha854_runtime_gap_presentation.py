"""Alpha8.54 regression for truthful runtime-gap presentation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).parents[1]
PIPELINE = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"


def _pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "kems_dashboard_pipeline_alpha854", PIPELINE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render(slots: list[dict]) -> str:
    module = _pipeline_module()
    card_yaml = module._plan_table_card(
        title="Alpha8.54 regression",
        attribute="today_slots",
        empty_message="No slots",
        indent="",
    )
    parsed = yaml.safe_load(card_yaml)
    assert isinstance(parsed, list) and len(parsed) == 1
    content = parsed[0]["content"]

    def state_attr(entity_id: str, attribute: str):
        assert entity_id == "sensor.kems_agile_slots"
        return slots if attribute == "today_slots" else []

    return (
        Environment(autoescape=False).from_string(content).render(state_attr=state_attr)
    )


def _slot(
    label: str,
    *,
    basis: str,
    actions: list[str],
    soc: float | None,
) -> dict:
    return {
        "label": label,
        "rate_pence": 15.91,
        "actions": actions,
        "flow_basis": basis,
        "flow_estimated_soc_percent": soc,
        "flow_grid_action": "IDLE",
        "flow_grid_kwh": 0.0,
        "flow_solar_action": "IDLE",
        "flow_solar_kwh": 0.0,
        "flow_battery_action": "IDLE",
        "flow_battery_kwh": 0.0,
    }


def test_historical_future_placeholder_renders_no_data_not_zero_activity() -> None:
    rendered = _render(
        [
            _slot(
                "12:00",
                basis="settled/replayed KEMS slot",
                actions=["future slot"],
                soc=None,
            )
        ]
    )

    assert (
        "| 12:00 | 15.91p | — | **NO DATA** · — | **NO DATA** · — | "
        "**NO DATA** · — |"
    ) in rendered
    assert "| 12:00 | 15.91p | — | **IDLE** · 0.00 kWh" not in rendered


def test_recorded_historical_idle_remains_idle_zero() -> None:
    rendered = _render(
        [
            _slot(
                "12:30",
                basis="settled/replayed KEMS slot",
                actions=[],
                soc=71.2,
            )
        ]
    )

    assert (
        "| 12:30 | 15.91p | 71.2% | **IDLE** · 0.00 kWh | "
        "**IDLE** · 0.00 kWh | **IDLE** · 0.00 kWh |"
    ) in rendered
    assert "NO DATA" not in rendered


def test_future_placeholder_is_not_mislabelled_as_historical_gap() -> None:
    rendered = _render(
        [
            _slot(
                "13:00",
                basis="KEMS forecast + final rolling allocation",
                actions=["future slot"],
                soc=72.5,
            )
        ]
    )

    assert (
        "| 13:00 | 15.91p | 72.5% | **IDLE** · 0.00 kWh | "
        "**IDLE** · 0.00 kWh | **IDLE** · 0.00 kWh |"
    ) in rendered
    assert "NO DATA" not in rendered


def test_gap_detection_reuses_existing_retained_evidence_contract() -> None:
    source = PIPELINE.read_text(encoding="utf-8")

    assert "settled/replayed KEMS slot" in source
    assert "p.get('actions') == ['future slot']" in source
    assert "NO DATA" in source
    assert "rolling_planned_battery_export_kwh" not in source
    assert "services.async_call" not in source
    assert "providers.foxess" not in source
