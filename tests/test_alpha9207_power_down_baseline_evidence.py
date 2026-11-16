"""Power Down bonus estimate is withheld unless both net-baseline meters agree."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components" / "kems" / "power_down.py"


def _baseline():
    """Import the pure physical-basis calculation without loading HA dispatch."""
    source = ast.parse(SOURCE.read_text(encoding="utf-8"))
    definitions = [
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_number", "_baseline_net_power_kw"}
    ]
    # With postponed annotations, no Home Assistant installation is required.
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *definitions],
        type_ignores=[],
    )
    namespace = {"math": __import__("math")}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace["_baseline_net_power_kw"]


def _sample(**overrides):
    beginning = datetime(2026, 11, 12, 17, tzinfo=UTC)
    data = {
        "saving_session_baseline_incomplete": False,
        "saving_session_import_baseline_period_kwh": 0.5,
        "saving_session_export_baseline_period_kwh": 0.2,
        "saving_session_baseline_period_start": beginning,
        "saving_session_baseline_period_end": beginning + timedelta(minutes=30),
        "saving_session_import_baseline_total_kwh": 1.0,
        "saving_session_export_baseline_total_kwh": 0.4,
        "saving_session_start": beginning,
        "saving_session_end": beginning + timedelta(hours=1),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_both_import_export_baseline_required_before_bonus_estimate():
    baseline = _baseline()
    assert baseline(_sample()) == 0.6
    assert baseline(_sample(saving_session_export_baseline_period_kwh=None, saving_session_export_baseline_total_kwh=None)) is None
    assert baseline(_sample(saving_session_import_baseline_period_kwh=None, saving_session_import_baseline_total_kwh=None)) is None
    assert baseline(_sample(saving_session_baseline_incomplete=True)) is None
    assert baseline(_sample(saving_session_export_baseline_period_kwh=float("nan"), saving_session_export_baseline_total_kwh=None)) is None


def test_valid_matched_total_fallback_remains_conservative():
    baseline = _baseline()
    assert baseline(_sample(saving_session_export_baseline_period_kwh=None)) == 0.6
    assert baseline(_sample(saving_session_export_baseline_period_kwh=None, saving_session_export_baseline_total_kwh=None)) is None
    assert baseline(_sample(saving_session_import_baseline_period_kwh=0.0, saving_session_export_baseline_period_kwh=1.0)) == -2.0
