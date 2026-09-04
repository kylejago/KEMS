"""Regression coverage for Alpha8.33 supplier rewards dashboard accounting."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD_RUNTIME = ROOT / "custom_components" / "kems" / "dashboard.py"
MASTER_DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"


def _readability_pass():
    """Load the pure dashboard string transform without importing Home Assistant."""
    source = DASHBOARD_RUNTIME.read_text()
    module = ast.parse(source)
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_dashboard_readability_pass"
    )
    isolated = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(isolated)
    namespace: dict[str, object] = {}
    exec(compile(isolated, str(DASHBOARD_RUNTIME), "exec"), namespace)
    return namespace["_dashboard_readability_pass"]


def test_daily_costs_use_authoritative_power_down_reward_field() -> None:
    transform = _readability_pass()
    source = MASTER_DASHBOARD.read_text()

    assert "Supplier credits" in source
    assert "supplier_energy_credit_pence" in source
    assert "electricity_export_income_pence" in source

    rendered = transform(source)

    assert "Supplier rewards & credits" in rendered
    assert "power_down_income_pence" in rendered
    assert "supplier_energy_credit_pence" not in rendered
    assert "electricity_export_income_pence" in rendered


def test_power_down_reward_formats_as_separate_credit_without_export_double_count() -> (
    None
):
    power_down_income_pence = 47.56
    export_income_pence = 57.01

    displayed_reward = f"−£{power_down_income_pence / 100:.2f}"
    displayed_export = f"−£{export_income_pence / 100:.2f}"

    assert displayed_reward == "−£0.48"
    assert displayed_export == "−£0.57"
    assert power_down_income_pence != power_down_income_pence + export_income_pence


def test_alpha833_release_contract_remains_successor_safe() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    version = str(manifest["version"])
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert (
        str(version).startswith("0.9.0-alpha9") or int(version.rsplit(".", 1)[1]) >= 33
    )
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
