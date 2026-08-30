from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "custom_components/kems/agile_control_alignment.py",
    '''        and not (\n            target["charge_kw"] > 1e-6 and target["total_discharge_kw"] > 1e-6\n        )\n''',
    '''        and not (target["charge_kw"] > 1e-6 and target["total_discharge_kw"] > 1e-6)\n''',
)
replace_once(
    "custom_components/kems/agile_control_alignment.py",
    '''            else (\n                "Feed-in First"\n                if target["battery_export_kw"] > 0.01\n                else "Self Use"\n            )\n''',
    '''            else ("Feed-in First" if target["battery_export_kw"] > 0.01 else "Self Use")\n''',
)
replace_once(
    "custom_components/kems/agile_smart_export.py",
    '''                    max(capacity - battery, 0.0)\n                    / max(config.charge_efficiency, 0.01),\n''',
    '''                    max(capacity - battery, 0.0) / max(config.charge_efficiency, 0.01),\n''',
)
replace_once(
    "tests/test_alpha855_routing_economics_shadow.py",
    '''    spec = importlib.util.spec_from_file_location("alpha855_discharge_slot_ledger", LEDGER)\n''',
    '''    spec = importlib.util.spec_from_file_location(\n        "alpha855_discharge_slot_ledger", LEDGER\n    )\n''',
)
replace_once(
    "tests/test_alpha855_routing_economics_shadow.py",
    '''def test_grid_residual_only_appears_after_protected_battery_budget_is_exhausted() -> None:\n''',
    '''def test_grid_residual_only_appears_after_protected_battery_budget_is_exhausted() -> (\n    None\n):\n''',
)
replace_once(
    "tests/test_alpha855_routing_economics_shadow.py",
    '''def test_surplus_solar_stores_when_marginal_future_net_value_is_genuinely_higher() -> None:\n''',
    '''def test_surplus_solar_stores_when_marginal_future_net_value_is_genuinely_higher() -> (\n    None\n):\n''',
)
replace_once(
    "tests/test_alpha855_routing_economics_shadow.py",
    '''    assert 'mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}' in ledger_source\n''',
    '''    assert (\n        'mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}'\n        in ledger_source\n    )\n''',
)
