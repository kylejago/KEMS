from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
FLOW = ROOT / "custom_components" / "kems" / "agile_flow_presentation.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
NOTES = ROOT / "docs" / "alpha8.57-release-notes.md"
TEST = ROOT / "tests" / "test_alpha857_house_first_reconciliation.py"
WORKFLOW = ROOT / ".github" / "workflows" / "apply-alpha857.yml"
SELF = Path(__file__)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


flow = FLOW.read_text()
flow = replace_once(
    flow,
    "_EPSILON = 1e-6\n_GRID_IMPORT_PRECISION_KWH = 0.001\n",
    "_EPSILON = 1e-6\n",
    "remove Alpha8.56 fixed precision threshold",
)
old_helper = '''def _close_home_precision_residual(\n    *,\n    remaining_house_kwh: float,\n    battery_home_kwh: float,\n    battery_energy_kwh: float,\n    floor_kwh: float,\n    discharge_limit_kwh: float,\n    discharge_efficiency: float,\n) -> float:\n    \"\"\"Close only quantisation-sized home residuals with usable battery.\"\"\"\n    remaining_house = max(remaining_house_kwh, 0.0)\n    battery_home = min(max(battery_home_kwh, 0.0), remaining_house)\n    residual = max(remaining_house - battery_home, 0.0)\n    if residual <= _EPSILON or residual > _GRID_IMPORT_PRECISION_KWH + _EPSILON:\n        return battery_home\n\n    discharge_headroom = max(discharge_limit_kwh - battery_home, 0.0)\n    battery_headroom = max(\n        (battery_energy_kwh - floor_kwh) * max(discharge_efficiency, 0.01),\n        0.0,\n    )\n    if min(discharge_headroom, battery_headroom) + _EPSILON < residual:\n        return battery_home\n    return remaining_house\n'''
new_helper = '''def _close_home_precision_residual(\n    *,\n    remaining_house_kwh: float,\n    battery_home_kwh: float,\n    battery_energy_kwh: float,\n    floor_kwh: float,\n    discharge_limit_kwh: float,\n    discharge_efficiency: float,\n) -> float:\n    \"\"\"Reconcile future daytime battery discharge to the house-first invariant.\n\n    ``battery_home_kwh`` remains in the signature for compatibility with the\n    Alpha8.56 regression boundary, but the canonical future projection must not\n    preserve a rounded/planned home allocation when physical battery headroom can\n    cover more of the house.  Outside cheap periods, usable battery AC therefore\n    serves the remaining house demand before Grid.\n    \"\"\"\n    del battery_home_kwh\n    remaining_house = max(remaining_house_kwh, 0.0)\n    battery_headroom = max(\n        (battery_energy_kwh - floor_kwh) * max(discharge_efficiency, 0.01),\n        0.0,\n    )\n    usable_discharge = min(\n        max(discharge_limit_kwh, 0.0),\n        battery_headroom,\n    )\n    return min(remaining_house, usable_discharge)\n'''
flow = replace_once(flow, old_helper, new_helper, "replace house reconciliation helper")
old_export = '''            battery_export = min(\n                battery_export,\n                max((battery - floor_kwh) * discharge_efficiency, 0.0),\n                max(export_limit, 0.0),\n            )\n'''
new_export = '''            battery_export = min(\n                battery_export,\n                max(discharge_limit - battery_home, 0.0),\n                max(inverter_limit - solar_home - battery_home, 0.0),\n                max((battery - floor_kwh) * discharge_efficiency, 0.0),\n                max(export_limit, 0.0),\n            )\n'''
flow = replace_once(
    flow,
    old_export,
    new_export,
    "cap export after house-first reconciliation",
)
FLOW.write_text(flow)

manifest = MANIFEST.read_text()
manifest = replace_once(
    manifest,
    '"version": "0.8.0-alpha8.56"',
    '"version": "0.8.0-alpha8.57"',
    "bump manifest version",
)
MANIFEST.write_text(manifest)

NOTES.write_text('''# KEMS 0.8.0-alpha8.57\n\nAlpha8.57 replaces the Alpha8.56 fixed 1 Wh precision tolerance with a canonical house-first discharge reconciliation proven from the 30 Aug Alpha8.56 field diagnostic.\n\n## Changed\n\n- Outside confirmed cheap/Intelligent import periods, canonical future routing now supplies remaining house demand from all physically usable battery AC headroom above the protected SOC floor before allowing Grid import.\n- A rounded or stale `planned_battery_to_home_kwh` value can no longer create a daytime Grid residual when the battery can physically cover the house.\n- When a planned battery export is already using the slot discharge/inverter ceiling, the canonical projection reduces that discretionary export before allowing Grid import for the house.\n- Planned battery export is never increased and the export-slot ranking itself is unchanged.\n- Genuine Grid import remains whenever solar plus physically permissible battery discharge cannot cover the house.\n\n## Field regressions\n\nThe regression reproduces the Alpha8.56 16:00 shape: 0.733 kWh house demand, 0.386 kWh solar-to-home, a rounded 0.342 kWh planned battery-to-home allocation and 2.767 kWh planned battery export. Canonical routing must top battery-to-home up to 0.347 kWh and publish zero Grid import while preserving the export because physical headroom exists.\n\nA second regression saturates total battery discharge and proves that an increased house requirement is funded by reducing battery export before Grid import. A third regression proves a real physical battery shortfall still appears as Grid import only after discretionary export has been reduced to zero.\n\n## Protected boundaries\n\nNo export price ranking, solar storage economics, reserve floor, Power Down, Happy Hour, EV policy, cheap-window routing, FoxESS commissioning or real hardware writes are changed. Real hardware writes remain blocked.\n''')

TEST.write_text(r'''"""Alpha8.57 regression for canonical house-first discharge reconciliation."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).parents[1]
FLOW = ROOT / "custom_components" / "kems" / "agile_flow_presentation.py"


def _projection_function(*, cheap: bool = False):
    tree = ast.parse(FLOW.read_text())
    wanted = {
        "_number",
        "_dt",
        "_effective_battery_home",
        "_effective_battery_export",
        "_forecast_solar_kwh",
        "_best_future_rate",
        "_conservative_house_kw",
        "_close_home_precision_residual",
        "_future_today_projection",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    agile = SimpleNamespace(
        LONDON=ZoneInfo("Europe/London"),
        BATTERY_WEAR_PENCE_PER_KWH=2.0,
        _in_window=lambda *_args: cheap,
        _next_cheap=lambda now, _tariff: now + timedelta(hours=12),
    )
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "math": math,
        "agile": agile,
        "SimulationConfig": Any,
        "LearnedState": Any,
        "SolarForecastState": Any,
        "ForecastPlanState": Any,
        "TariffSettings": Any,
        "_EPSILON": 1e-6,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, FLOW.as_posix(), "exec"), namespace)
    return namespace["_future_today_projection"]


def _project(
    *,
    house_kw: float,
    solar_hour_kwh: float,
    planned_home_kwh: float,
    planned_export_kwh: float,
    max_discharge_kw: float = 7.0,
    inverter_limit_kw: float = 7.0,
    soc_percent: float = 78.0,
):
    project = _projection_function()
    slot_start = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)
    state = {
        "today_slots": [
            {
                "valid_from": slot_start.isoformat(),
                "valid_to": (slot_start + timedelta(minutes=30)).isoformat(),
                "rate_pence": 19.51,
                "planned_battery_to_home_kwh": planned_home_kwh,
                "rolling_planned_battery_export_kwh": planned_export_kwh,
                "battery_export_kwh": planned_export_kwh,
            }
        ],
        "current_routing_snapshot": {"simulated_soc_percent": soc_percent},
    }
    config = SimpleNamespace(
        battery_capacity_kwh=56.42,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        battery_reserve_percent=10.0,
        max_discharge_kw=max_discharge_kw,
        inverter_limit_kw=inverter_limit_kw,
        export_limit_kw=7.0,
        max_charge_kw=7.0,
        site_import_limit_kw=None,
    )
    learned = SimpleNamespace(typical_house_load_kw=house_kw)
    forecast = SimpleNamespace(
        hourly=[
            SimpleNamespace(
                timestamp=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
                solar_energy_kwh=solar_hour_kwh,
            )
        ]
    )
    forecast_plan = SimpleNamespace(
        minimum_precheap_soc_percent=10.0,
        maximum_overnight_soc_percent=100.0,
    )
    tariff = SimpleNamespace(offpeak_start=time(23, 30), offpeak_end=time(5, 30))
    owner = SimpleNamespace(
        _kems_solar_net_house_protection={"conservative_house_kw": house_kw}
    )
    output = project(
        owner,
        state,
        now=datetime(2026, 8, 30, 14, 45, tzinfo=UTC),
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )
    return output[slot_start.isoformat()]


def test_field_export_slot_closes_multi_wh_house_residual_before_grid() -> None:
    """Reproduce the Alpha8.56 16:00 import/export field shape."""
    projection = _project(
        house_kw=1.466,
        solar_hour_kwh=0.772,
        planned_home_kwh=0.342,
        planned_export_kwh=2.767,
    )
    assert projection["solar_to_home_kwh"] == pytest.approx(0.386)
    assert projection["battery_to_home_kwh"] == pytest.approx(0.347)
    assert projection["battery_export_kwh"] == pytest.approx(2.767)
    assert projection["grid_import_kwh"] == 0.0


def test_house_wins_by_reducing_export_when_discharge_ceiling_is_full() -> None:
    """Discretionary export must be transferred to home before Grid import."""
    projection = _project(
        house_kw=1.6,
        solar_hour_kwh=0.0,
        planned_home_kwh=0.7,
        planned_export_kwh=2.8,
    )
    assert projection["battery_to_home_kwh"] == pytest.approx(0.8)
    assert projection["battery_export_kwh"] == pytest.approx(2.7)
    assert projection["grid_import_kwh"] == 0.0
    assert projection["battery_to_home_kwh"] + projection["battery_export_kwh"] == pytest.approx(3.5)


def test_real_physical_shortfall_imports_only_after_export_is_removed() -> None:
    """Grid remains valid only when the battery cannot physically cover the house."""
    projection = _project(
        house_kw=8.0,
        solar_hour_kwh=0.0,
        planned_home_kwh=0.5,
        planned_export_kwh=2.5,
    )
    assert projection["battery_to_home_kwh"] == pytest.approx(3.5)
    assert projection["battery_export_kwh"] == 0.0
    assert projection["grid_import_kwh"] == pytest.approx(0.5)
''')

# The helper mechanism must not survive in the candidate tree.
WORKFLOW.unlink(missing_ok=True)
SELF.unlink(missing_ok=True)
