"""Regression coverage for alpha7.15 Agile historical recovery."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _string_constant(path: Path, name: str) -> str:
    """Read one literal module constant without importing Home Assistant."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError(f"{name} was not found in {path}")


def test_energy_source_parser_supports_current_and_legacy_grid_shapes() -> None:
    """Energy fallback must accept both generations of HA grid preferences."""
    source = (INTEGRATION / "agile_alpha715_backfill.py").read_text(encoding="utf-8")
    assert 'source.get("flow_from")' in source
    assert 'source.get("flow_to")' in source
    assert '"stat_energy_from"' in source
    assert '"stat_energy_to"' in source
    assert "_ORIGINAL_ENERGY_SOURCES(values)" in source


def test_backfill_diagnostics_are_published_as_normal_entities() -> None:
    """History diagnostics must remain visible even if Markdown templating fails."""
    source = (INTEGRATION / "agile_alpha715_backfill.py").read_text(encoding="utf-8")
    for entity_id in (
        "sensor.kems_agile_backfill_method",
        "sensor.kems_agile_backfill_reason",
        "sensor.kems_agile_backfill_direct_sources",
        "sensor.kems_agile_backfill_grid_import",
        "sensor.kems_agile_backfill_grid_export",
        "sensor.kems_agile_backfill_solar",
        "sensor.kems_agile_backfill_battery_discharge",
        "sensor.kems_agile_backfill_battery_charge",
        "sensor.kems_agile_backfill_battery_soc",
    ):
        assert entity_id in source
    assert "Historical data available" in source
    assert "Configured — no usable history yet" in source


def test_runtime_installs_alpha715_after_enhanced_backfill() -> None:
    """Compatibility patch must wrap the enhanced backfill implementation."""
    source = (INTEGRATION / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    assert "install_alpha715_backfill_patch()" in source
    assert "install_alpha715_dashboard_patch()" in source
    assert source.index("install_enhanced_backfill()") < source.index(
        "install_alpha715_backfill_patch()"
    )
    assert source.index("install_alpha714_dashboard_patch()") < source.index(
        "install_alpha715_dashboard_patch()"
    )


def test_sensor_backed_diagnostics_card_is_valid_yaml() -> None:
    """Replacing the old Markdown block must preserve the dashboard YAML shape."""
    old = _string_constant(
        INTEGRATION / "agile_alpha714_dashboard.py",
        "_BACKFILL_DIAGNOSTICS_CARD",
    )
    new = _string_constant(
        INTEGRATION / "agile_alpha715_dashboard.py",
        "_BACKFILL_DIAGNOSTICS_ENTITIES_CARD",
    )
    sample = f"""title: KEMS Master Dashboard
views:
  - title: Agile History
    path: agile-history
    cards:
{old}
      - type: history-graph
        title: Cumulative Agile advantage
        entities: []
"""
    replaced = sample.replace(old, new, 1)
    parsed = yaml.safe_load(replaced)
    view = parsed["views"][0]
    assert view["path"] == "agile-history"
    cards = view["cards"]
    diagnostics = next(
        card for card in cards if card.get("title") == "Historical backfill diagnostics"
    )
    assert diagnostics["type"] == "entities"
    assert any(
        item.get("entity") == "sensor.kems_agile_backfill_reason"
        for item in diagnostics["entities"]
    )
