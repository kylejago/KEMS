"""Regression tests for the HACS package layout."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def test_all_runtime_code_is_inside_integration_directory() -> None:
    """HACS only installs the integration directory."""
    assert not (ROOT / "kems_core").exists()
    assert (INTEGRATION / "kems_core" / "models.py").is_file()
    assert (INTEGRATION / "providers" / "foxess.py").is_file()
    assert (INTEGRATION / "entity_discovery.py").is_file()


def test_no_absolute_kems_core_imports_in_runtime_code() -> None:
    """Runtime modules must use package-relative imports."""
    offenders: list[str] = []

    for path in INTEGRATION.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "kems_core" for alias in node.names
            ):
                offenders.append(f"{path}: import kems_core")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and (node.module or "").startswith("kems_core")
            ):
                offenders.append(f"{path}: from {node.module} import ...")

    assert offenders == []


def test_repository_contains_no_python_cache_files() -> None:
    """Compiled cache files must never be shipped through HACS."""
    assert list(INTEGRATION.rglob("*.pyc")) == []
    assert [path for path in INTEGRATION.rglob("__pycache__") if path.is_dir()] == []


def test_all_relative_runtime_imports_resolve_to_source_files() -> None:
    """Every package-relative runtime import must point to a shipped module."""
    missing: list[str] = []

    for path in INTEGRATION.rglob("*.py"):
        relative = path.relative_to(INTEGRATION).with_suffix("")
        parts = list(relative.parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()

        module_name = ".".join(["custom_components", "kems", *parts])
        package_name = module_name if is_package else module_name.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue

            relative_name = f"{'.' * node.level}{node.module or ''}"
            target = importlib.util.resolve_name(relative_name, package_name)
            prefix = "custom_components.kems"
            if target == prefix:
                continue
            if not target.startswith(f"{prefix}."):
                missing.append(f"{path}:{node.lineno} resolves outside KEMS: {target}")
                continue

            target_parts = target.split(".")[2:]
            module_path = INTEGRATION.joinpath(*target_parts).with_suffix(".py")
            package_path = INTEGRATION.joinpath(*target_parts, "__init__.py")
            if not module_path.is_file() and not package_path.is_file():
                missing.append(f"{path}:{node.lineno} missing target: {target}")

    assert missing == []


def test_manifest_classifies_kems_as_hub() -> None:
    """KEMS must appear under Integrations rather than Helpers."""
    import json

    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["integration_type"] == "hub"
    assert str(manifest["version"]).strip()


def test_alpha4_preserves_history_and_versions_simulation_ledger() -> None:
    """Observed history must survive while alpha4 simulation value can reset."""
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    history_source = (INTEGRATION / "history.py").read_text(encoding="utf-8")
    lifetime_source = (INTEGRATION / "lifetime.py").read_text(encoding="utf-8")

    assert 'STORAGE_NAMESPACE = "clean_v6_alpha2"' in const_source
    assert "SIMULATION_LEDGER_VERSION = 5" in const_source
    assert "STORAGE_NAMESPACE" in history_source
    assert "simulation_ledger_version" in lifetime_source
    assert "ledger_schema_version" in lifetime_source
    assert "should_accumulate_lifetime_value" in lifetime_source
    assert "period_summaries" in lifetime_source
    assert "daily_records" in lifetime_source
    assert (
        "include_commissioned_value=not rebuilding_existing_ledger" in lifetime_source
    )


def test_entry_migration_applies_kh7_paced_export_defaults() -> None:
    """Existing alpha2 entries should be migrated without manual option edits."""
    source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")

    assert "VERSION = 13" in config_flow
    assert "options[CONF_INVERTER_LIMIT] = 7.0" in source
    assert "options[CONF_MAX_CHARGE] = 7.0" in source
    assert "options[CONF_MAX_DISCHARGE] = 7.0" in source
    assert "options[CONF_EXPORT_RATE] = 12.0" in source
    assert 'options[CONF_SIMULATION_STRATEGY] = "paced_export"' in source


def test_alpha4_ships_octoplus_power_down_provider() -> None:
    """The HACS package must contain the joined-session source provider."""
    assert (INTEGRATION / "providers" / "octoplus.py").is_file()
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    assert "CONF_SAVING_SESSION_EVENTS" in const_source
    assert "CONF_SAVING_SESSION_IMPORT_BASELINE" in const_source
    assert "CONF_SAVING_SESSION_EXPORT_BASELINE" in const_source


def test_control_lab_platforms_are_shipped() -> None:
    """Interactive simulation controls must be available in Home Assistant."""
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert (INTEGRATION / "select.py").is_file()
    assert (INTEGRATION / "switch.py").is_file()
    assert (INTEGRATION / "runtime_options.py").is_file()
    assert (INTEGRATION / "power_down.py").is_file()
    assert "Platform.SELECT" in init_source
    assert "Platform.SWITCH" in init_source


def test_alpha4_migration_preserves_live_tariff_and_adds_manual_fallback() -> None:
    """Existing alpha3 users should keep automatic pricing after migration."""
    source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")

    assert 'options.setdefault(CONF_TARIFF_MODE, "automatic")' in source
    assert "options.setdefault(CONF_MANUAL_DAY_RATE, 28.3036)" in source
    assert "options.setdefault(CONF_MANUAL_OFFPEAK_RATE, 3.4933)" in source
    assert 'CONF_MANUAL_OFFPEAK_START: "23:30:00"' in const_source
    assert 'CONF_MANUAL_OFFPEAK_END: "05:30:00"' in const_source


def test_alpha5_migration_preserves_existing_export_behaviour() -> None:
    """Alpha4 users must not silently switch to no-export mode."""
    source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert 'options.setdefault(CONF_EXPORT_TARIFF_STATUS, "active")' in source
    assert "version=13" in source
