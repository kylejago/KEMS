"""Alpha8.77 commissioning-readiness cleanup regression contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
INIT = KEMS / "__init__.py"
COMMISSIONING = KEMS / "commissioning.py"
DISPATCH = KEMS / "agile_dispatch_reconciliation.py"
COMPAT = KEMS / "agile_alpha7_compat.py"
SOURCE_AUTHORITY = KEMS / "source_authority.py"


def test_setup_uses_one_deterministic_source_authority_reconciliation() -> None:
    """Validated mappings should not be overwritten by raw discovery on restart."""
    source = INIT.read_text(encoding="utf-8")

    assert "async_reconcile_source_mappings" in source
    assert "authority = await async_reconcile_source_mappings" in source
    assert "final_validation = await async_validate_entity_mappings" in source
    assert "enriched = {**validation.accepted, **discovery.mappings}" not in source


def test_source_authority_only_promotes_to_a_higher_priority_platform() -> None:
    """Automatic source changes must be platform promotions, not peer churn."""
    source = SOURCE_AUTHORITY.read_text(encoding="utf-8")

    assert "_platform_rank" in source
    assert "discovered_platform" in source
    assert "existing_platform" in source
    assert "discovered_platform) >= _platform_rank" in source
    assert "PHYSICAL_SOURCE_KEYS" in source
    assert "duplicate_physical_sources" in source


def test_commissioning_requires_unique_physical_source_roles() -> None:
    """Duplicate commissioned telemetry must block FoxESS evidence collection."""
    source = COMMISSIONING.read_text(encoding="utf-8")

    assert '"physical_source_uniqueness"' in source
    assert "Duplicate commissioned physical source mapping" in source
    assert "Pre-install fallback shares physical roles" in source
    assert '"physical_source_authority": physical_source_authority' in source
    assert '"duplicate_physical_sources": {' in source
    assert '"physical_source_uniqueness",' in source
    assert '"real_hardware_writes": "blocked"' in source


def test_dispatch_diagnostic_has_no_obsolete_second_reserve_target() -> None:
    """Commissioning evidence must expose the canonical 15/10/12 hierarchy only."""
    source = DISPATCH.read_text(encoding="utf-8")

    assert '"battery_reserve_target_soc_percent"' not in source
    assert '"planning_target_soc_percent": planning_target' in source
    assert 'rolling_plan.get("hard_safety_floor_soc_percent")' in source
    assert 'rolling_plan.get("hard_safety_recovery_soc_percent")' in source
    assert '"reserve_hierarchy_source": "final rolling_export_plan"' in source
    assert '"hardware_writes": "blocked"' in source


def test_frozen_alpha7_regression_evidence_remains_non_runtime() -> None:
    """Historical files stay as evidence; live registries remain canonical names."""
    source = COMPAT.read_text(encoding="utf-8")
    normalised = " ".join(source.split())

    assert (
        "Historical version-named modules remain packaged regression evidence" in source
    )
    assert "New Alpha8 behaviour must be implemented in canonical modules" in normalised
    assert "agile_alpha730" not in source
    assert "agile_alpha8" not in source


def test_alpha877_release_contract_is_successor_safe() -> None:
    """Later Alpha8 releases must preserve the Alpha8.77 commissioning invariants."""
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )

    version = str(manifest["version"])
    assert version.startswith("0.8.0-alpha8.")
    assert int(version.rsplit(".", 1)[1]) >= 77
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    reason = bundle["maintenance"]["reason"].lower()
    assert "15%" in reason and "10%" in reason and "12%" in reason
    assert "hardware writes" in reason and "blocked" in reason
