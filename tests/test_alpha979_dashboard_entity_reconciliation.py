"""Alpha9.79 managed-dashboard entity reconciliation regressions."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
MASTER_SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
MASTER_PACKAGED = INTEGRATION / "kems_master_dashboard.yaml"
ROI_PACKAGED = INTEGRATION / "kems_roi_lifetime_dashboard.yaml"

ENTITY_RE = re.compile(
    r"\b(?:sensor|binary_sensor|select|switch|time|datetime|update)\.kems_[a-z0-9_]+"
)

STALE_ENTITY_IDS = {
    "sensor.kems_solar_generation_today",
    "sensor.kems_lifetime_gas_usage",
    "sensor.kems_lifetime_total_energy_cost",
    "sensor.kems_financial_export_income",
    "sensor.kems_financial_solar_generation",
    "sensor.kems_financial_grid_import",
    "sensor.kems_financial_grid_export",
    "sensor.kems_financial_house_consumption",
    "sensor.kems_simulated_battery_charge_today",
    "sensor.kems_agile_rolling_export_plan",
}


def _slugify(value: str) -> str:
    """Return the KEMS entity-name slug used by these static declarations."""
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


STABLE_REGISTRY_ALIASES = {
    # These long-lived entity IDs are preserved by Home Assistant's entity registry
    # even though their current friendly names/unique keys no longer slug to them.
    "select.kems_operating_mode",
    "sensor.kems_agile_happy_hour_plan",
    "sensor.kems_observed_cost_today",
    "sensor.kems_simulated_kems_cost_today",
}


RECONCILED_ENTITY_IDS = {
    "sensor.kems_observed_solar_generation_today",
    "sensor.kems_lifetime_gas_consumption",
    "sensor.kems_lifetime_net_energy_cost",
    "sensor.kems_paid_export_income_since_commissioning",
    "sensor.kems_solar_generation_since_commissioning",
    "sensor.kems_grid_import_since_commissioning",
    "sensor.kems_grid_export_since_commissioning",
    "sensor.kems_house_electricity_since_commissioning",
    "sensor.kems_simulated_battery_charged_today",
}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _literal_keyword(node: ast.Call, keyword: str) -> str | None:
    for item in node.keywords:
        if item.arg != keyword:
            continue
        if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
            return item.value.value
    return None


def _class_domain(node: ast.ClassDef) -> str | None:
    tokens = [node.name]
    for base in node.bases:
        if isinstance(base, ast.Name):
            tokens.append(base.id)
        elif isinstance(base, ast.Attribute):
            tokens.append(base.attr)
    joined = " ".join(tokens).lower()
    if "binarysensor" in joined:
        return "binary_sensor"
    if "datetime" in joined:
        return "datetime"
    if "sensor" in joined:
        return "sensor"
    if "switch" in joined:
        return "switch"
    if "select" in joined:
        return "select"
    if "update" in joined:
        return "update"
    if "time" in joined:
        return "time"
    return None


def _registered_entity_ids() -> set[str]:
    """Infer KEMS entity IDs from the integration's actual entity declarations."""
    result: set[str] = set()

    for path in INTEGRATION.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call = _call_name(node)
                name = _literal_keyword(node, "name")
                if name is None or "EntityDescription" not in call:
                    continue
                if "BinarySensor" in call:
                    domain = "binary_sensor"
                elif "Sensor" in call:
                    domain = "sensor"
                else:
                    continue
                result.add(f"{domain}.kems_{_slugify(name)}")

            if not isinstance(node, ast.ClassDef):
                continue
            domain = _class_domain(node)
            if domain is None:
                continue
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Name) and target.id == "_attr_name"
                    for target in statement.targets
                ):
                    continue
                if isinstance(statement.value, ast.Constant) and isinstance(
                    statement.value.value, str
                ):
                    result.add(f"{domain}.kems_{_slugify(statement.value.value)}")
    result.update(STABLE_REGISTRY_ALIASES)
    return result


def _managed_dashboard_refs() -> set[str]:
    text = (
        MASTER_SOURCE.read_text(encoding="utf-8")
        + "\n"
        + ROI_PACKAGED.read_text(encoding="utf-8")
    )
    return set(ENTITY_RE.findall(text))


def test_alpha979_removes_all_observed_stale_dashboard_entity_ids() -> None:
    text = (
        MASTER_SOURCE.read_text(encoding="utf-8")
        + "\n"
        + ROI_PACKAGED.read_text(encoding="utf-8")
    )
    for entity_id in STALE_ENTITY_IDS:
        assert entity_id not in text

    for entity_id in RECONCILED_ENTITY_IDS:
        assert entity_id in text


def test_alpha979_observed_solar_today_is_a_registered_sensor() -> None:
    source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert 'key="actual_solar_generation_today"' in source
    assert 'name="Observed solar generation today"' in source
    assert "data.simulation.actual_solar_generation_kwh" in source
    assert "sensor.kems_observed_solar_generation_today" in _registered_entity_ids()


def test_alpha979_managed_dashboard_refs_are_registered_by_kems() -> None:
    registered = _registered_entity_ids()
    refs = _managed_dashboard_refs()
    missing = sorted(refs - registered)
    assert (
        not missing
    ), f"Managed dashboard references unregistered KEMS entities: {missing}"


def test_alpha979_packaged_master_matches_repository_source() -> None:
    assert MASTER_PACKAGED.read_bytes() == MASTER_SOURCE.read_bytes()
