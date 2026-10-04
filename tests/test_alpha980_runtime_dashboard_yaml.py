"""Alpha9.80 runtime dashboard YAML hotfix regressions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MASTER_SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
CONTRACT = ROOT / "custom_components" / "kems" / "alpha937_dashboard_contract.py"


def _load_contract_module():
    spec = importlib.util.spec_from_file_location(
        "kems_alpha937_contract_test", CONTRACT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_alpha980_runtime_repaired_master_dashboard_is_valid_yaml() -> None:
    module = _load_contract_module()
    repaired = module.repair_dashboard_contract(MASTER_SOURCE.read_bytes())
    parsed = yaml.safe_load(repaired.decode())
    assert isinstance(parsed, dict)
    assert parsed.get("title") == "KEMS"
    assert isinstance(parsed.get("views"), list)


def test_alpha980_live_energy_markdown_table_remains_inside_block_scalar() -> None:
    module = _load_contract_module()
    repaired = module.repair_dashboard_contract(MASTER_SOURCE.read_bytes()).decode()
    assert "content: |\n          | Energy | Live Data |" in repaired
    assert "content: |\n                    | Energy | Live Data |" not in repaired
