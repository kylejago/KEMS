"""Alpha8 consolidation history plus the current coordinated release contract.

The historical tests keep the proven Alpha7.52 compatibility boundary intact while
current release assertions prove the independently versioned Alpha9 product tracks.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _compat_specs() -> list[tuple[str, str]]:
    source = (KEMS / "agile_alpha7_compat.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id not in {"PRE_BASE_PATCHES", "POST_BASE_PATCHES"}:
            continue
        assert isinstance(node.value, ast.Tuple)
        for item in node.value.elts:
            assert isinstance(item, ast.Tuple) and len(item.elts) == 2
            module = ast.literal_eval(item.elts[0])
            installer = ast.literal_eval(item.elts[1])
            specs.append((module, installer))
    return specs


def test_current_release_family_is_coordinated() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release/kems-bundle.template.json").read_text(encoding="utf-8")
    )
    panel_manager = (KEMS / "panel.py").read_text(encoding="utf-8")
    panel_yaml = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.0"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    pi_versions = {
        str(bundle["components"][key]["version"])
        for key in ("property_web", "pi_agent")
    }
    assert pi_versions == {"0.9.0-alpha9-web.0"}
    assert bundle["components"]["public_web"]["version"] == (
        "0.9.0-alpha9-public.0"
    )
    assert 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.0"' in panel_manager
    assert 'panel_config_version: "0.9.0-alpha9-panel.0"' in panel_yaml
    assert not (KEMS / "panel_ev_policy.py").exists()


def test_runtime_entrypoint_has_one_executable_alpha7_compatibility_boundary() -> None:
    runtime_path = KEMS / "agile_smart_export_runtime.py"
    source = runtime_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(runtime_path))

    compat_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "agile_alpha7_compat"
    ]
    assert len(compat_imports) == 1
    assert [alias.name for alias in compat_imports[0].names] == [
        "install_alpha7_compatibility"
    ]

    executable_calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert executable_calls.count("install_alpha7_compatibility") == 1
    assert not any(
        name.startswith("install_alpha7") and name != "install_alpha7_compatibility"
        for name in executable_calls
    )

    assert "ALPHA7_COMPATIBILITY_ORDER" in source


def test_alpha8_compatibility_registry_is_complete_and_resolvable() -> None:
    specs = _compat_specs()
    assert specs
    assert len(specs) == len(set(specs)), "Compatibility installers must be unique"
    assert specs[0] == ("agile_smart_export_reporting", "install_reporting_patch")

    runtime_reconciliation = (
        "agile_runtime_reconciliation",
        "install_runtime_reconciliation",
    )
    solar_net_demand = (
        "agile_solar_net_demand",
        "install_solar_net_demand",
    )
    total_discharge_ledger = (
        "agile_total_discharge_ledger",
        "install_total_discharge_ledger",
    )
    deadline_dominance = (
        "agile_deadline_dominance",
        "install_deadline_dominance",
    )
    assert specs.index(runtime_reconciliation) < specs.index(solar_net_demand)
    assert specs.index(solar_net_demand) < specs.index(total_discharge_ledger)
    assert specs.index(total_discharge_ledger) < specs.index(deadline_dominance)
    assert specs[-1] == deadline_dominance

    for module_name, installer_name in specs:
        path = KEMS / f"{module_name}.py"
        assert path.is_file(), f"Missing compatibility module {module_name}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert installer_name in functions, f"{module_name} is missing {installer_name}"


def test_event_priority_retires_alpha743_from_execution() -> None:
    specs = _compat_specs()
    operator_telemetry = ("agile_operator_telemetry", "install_operator_telemetry")
    event_priority = ("agile_event_priority", "install_event_priority")
    dashboard_parity = ("agile_dashboard_parity", "install_dashboard_parity")

    assert specs.index(event_priority) > specs.index(operator_telemetry)
    assert specs.index(event_priority) < specs.index(dashboard_parity)

    retired = "agile_alpha743_event_priority"
    assert not any(module_name == retired for module_name, _ in specs)

    historical = KEMS / f"{retired}.py"
    canonical_runtime = KEMS / "agile_event_priority_runtime.py"
    canonical_facade = KEMS / "agile_event_priority.py"
    assert historical.is_file()
    assert canonical_runtime.is_file()
    assert canonical_facade.is_file()
    assert canonical_runtime.read_text(encoding="utf-8") == historical.read_text(
        encoding="utf-8"
    )

    facade = canonical_facade.read_text(encoding="utf-8")
    assert "agile_event_priority_runtime" in facade
    assert "agile_alpha743_event_priority" not in facade


def test_dashboard_parity_retires_alpha744_from_execution() -> None:
    specs = _compat_specs()
    event_priority = ("agile_event_priority", "install_event_priority")
    dashboard_parity = ("agile_dashboard_parity", "install_dashboard_parity")
    progressive = (
        "agile_progressive_publication",
        "install_progressive_publication_planning",
    )
    assert specs.index(dashboard_parity) > specs.index(event_priority)
    assert specs.index(dashboard_parity) < specs.index(progressive)

    retired = "agile_alpha744_dashboard_parity"
    assert not any(module_name == retired for module_name, _ in specs)
    assert (KEMS / f"{retired}.py").is_file()


def test_progressive_publication_retires_alpha745_and_alpha746_from_execution() -> None:
    specs = _compat_specs()
    dashboard_parity = ("agile_dashboard_parity", "install_dashboard_parity")
    progressive = (
        "agile_progressive_publication",
        "install_progressive_publication_planning",
    )
    full_battery = ("agile_full_battery_routing", "install_full_battery_routing")

    assert specs.index(progressive) > specs.index(dashboard_parity)
    assert specs.index(progressive) < specs.index(full_battery)

    retired = {
        "agile_alpha745_plan_clarity",
        "agile_alpha746_no_unknown_reserve",
    }
    assert not any(module_name in retired for module_name, _ in specs)
    assert all((KEMS / f"{module_name}.py").is_file() for module_name in retired)

    reporting = (KEMS / "agile_publication_reporting.py").read_text(encoding="utf-8")
    assert "agile_progressive_publication" in reporting
    assert "agile_alpha745_plan_clarity" not in reporting
    assert "agile_alpha746_no_unknown_reserve" not in reporting


def test_full_battery_routing_retires_alpha748_from_execution() -> None:
    specs = _compat_specs()
    progressive = (
        "agile_progressive_publication",
        "install_progressive_publication_planning",
    )
    full_battery = ("agile_full_battery_routing", "install_full_battery_routing")
    deadline_coverage = (
        "agile_deadline_plan_reconciliation",
        "install_deadline_plan_coverage",
    )

    assert specs.index(full_battery) > specs.index(progressive)
    assert specs.index(full_battery) < specs.index(deadline_coverage)

    retired = "agile_alpha748_full_battery_solar"
    assert not any(module_name == retired for module_name, _ in specs)
    assert (KEMS / f"{retired}.py").is_file()


def test_deadline_reconciliation_retires_alpha749_and_alpha751_from_execution() -> None:
    specs = _compat_specs()
    full_battery = ("agile_full_battery_routing", "install_full_battery_routing")
    deadline_coverage = (
        "agile_deadline_plan_reconciliation",
        "install_deadline_plan_coverage",
    )
    no_reserve = ("agile_publication_reporting", "install_no_reserve_reporting")
    maximum_discharge = (
        "agile_deadline_plan_reconciliation",
        "install_maximum_discharge_plan_reconcile",
    )
    tomorrow = (
        "agile_publication_reporting",
        "install_tomorrow_publication_reporting",
    )

    assert specs.index(deadline_coverage) > specs.index(full_battery)
    assert specs.index(deadline_coverage) < specs.index(no_reserve)
    assert specs.index(maximum_discharge) > specs.index(no_reserve)
    assert specs.index(maximum_discharge) < specs.index(tomorrow)

    retired = {
        "agile_alpha749_deadline_plan_coverage",
        "agile_alpha751_maximum_discharge_plan_reconcile",
    }
    assert not any(module_name in retired for module_name, _ in specs)
    assert all((KEMS / f"{module_name}.py").is_file() for module_name in retired)


def test_publication_reporting_retires_alpha750_and_alpha752_from_execution() -> None:
    specs = _compat_specs()
    deadline_coverage = (
        "agile_deadline_plan_reconciliation",
        "install_deadline_plan_coverage",
    )
    no_reserve = ("agile_publication_reporting", "install_no_reserve_reporting")
    maximum_discharge = (
        "agile_deadline_plan_reconciliation",
        "install_maximum_discharge_plan_reconcile",
    )
    tomorrow = (
        "agile_publication_reporting",
        "install_tomorrow_publication_reporting",
    )
    reconciliation = (
        "agile_dispatch_reconciliation",
        "install_dispatch_reconciliation",
    )

    assert specs.index(no_reserve) > specs.index(deadline_coverage)
    assert specs.index(no_reserve) < specs.index(maximum_discharge)
    assert specs.index(tomorrow) > specs.index(maximum_discharge)
    assert specs.index(reconciliation) > specs.index(tomorrow)

    retired = {
        "agile_alpha750_no_reserve_reporting",
        "agile_alpha752_tomorrow_no_reserve_rounding",
    }
    assert not any(module_name in retired for module_name, _ in specs)
    assert all((KEMS / f"{module_name}.py").is_file() for module_name in retired)


def test_canonical_event_priority_preserves_dispatch_and_hardware_boundary() -> None:
    facade = (KEMS / "agile_event_priority.py").read_text(encoding="utf-8")
    runtime = (KEMS / "agile_event_priority_runtime.py").read_text(encoding="utf-8")

    assert "install_event_priority" in facade
    assert "agile_event_priority_runtime" in facade
    assert "_dispatch_targets" in runtime
    assert "_rolling_plan" in runtime
    assert "safety > Power Down > Happy Hour > Agile price" in runtime
    assert '"hardware_writes": "blocked"' in runtime
    assert ".services.async_call(" not in facade + runtime
    assert "providers.foxess" not in facade + runtime
    assert "safe_to_write_hardware = True" not in facade + runtime
    assert "commands_permitted = True" not in facade + runtime


def test_canonical_dashboard_parity_cannot_change_dispatch_or_hardware_writes() -> None:
    source = (KEMS / "agile_dashboard_parity.py").read_text(encoding="utf-8")
    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_canonical_progressive_publication_cannot_enable_hardware_writes() -> None:
    source = (KEMS / "agile_progressive_publication.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_canonical_full_battery_routing_cannot_enable_hardware_writes() -> None:
    source = (KEMS / "agile_full_battery_routing.py").read_text(encoding="utf-8")
    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source


def test_canonical_deadline_reconciliation_cannot_enable_hardware_writes() -> None:
    source = (KEMS / "agile_deadline_plan_reconciliation.py").read_text(
        encoding="utf-8"
    )
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_canonical_publication_reporting_cannot_enable_hardware_writes() -> None:
    source = (KEMS / "agile_publication_reporting.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "hardware-write permissions remain untouched" in source


def test_final_dispatch_reconciliation_cannot_enable_hardware_writes() -> None:
    source = (KEMS / "agile_dispatch_reconciliation.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source


def test_alpha8_does_not_restart_version_named_patch_debt() -> None:
    offenders = sorted(path.name for path in KEMS.glob("agile_alpha8*.py"))
    assert offenders == [], (
        "Alpha8 behaviour belongs in canonical Agile modules, not another "
        f"version-named patch chain: {offenders}"
    )


def test_alpha8_is_newer_than_the_frozen_alpha7_baseline() -> None:
    source = (KEMS / "versioning.py").read_text(encoding="utf-8")
    namespace: dict[str, object] = {}
    exec(compile(source, "versioning.py", "exec"), namespace)
    relation = namespace["version_relation"]
    assert callable(relation)
    assert relation("0.8.0-alpha8.0", "0.7.0-alpha7.52") == 1
