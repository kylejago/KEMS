"""Guarded one-shot Alpha9.30 test-contract and fallback fix; remove before freeze."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Preserve the Octopus signed-demand fallback. Aggregate KH7 energy entities are
# already rejected by their unit/device class plus the remaining total/today tokens.
discovery = ROOT / "custom_components/kems/entity_discovery.py"
text = discovery.read_text(encoding="utf-8")
energy_token = '            "energy",\n'
if text.count(energy_token) != 2:
    raise RuntimeError(
        f"entity_discovery.py: expected two temporary energy exclusions, found {text.count(energy_token)}"
    )
discovery.write_text(text.replace(energy_token, "", 2), encoding="utf-8")

# Established current-release assertions move mechanically to Alpha9.30.
current_release_tests = (
    "tests/test_alpha8_consolidation.py",
    "tests/test_alpha913_forecast_path_scheduler.py",
    "tests/test_alpha919_runtime_recorder_owner.py",
    "tests/test_alpha920_shadow_recorder_owner.py",
    "tests/test_alpha921_planning_target_house_floor.py",
    "tests/test_alpha922_flow_contract_startup.py",
    "tests/test_alpha924_flow_parity_export_floor.py",
    "tests/test_alpha925_observability_clarity.py",
    "tests/test_alpha926_panel_layout_profiles.py",
    "tests/test_alpha927_policy_label_publication.py",
    "tests/test_alpha928_panel_v2_staggered_flow.py",
    "tests/test_alpha929_panel_v2_extra_gap.py",
    "tests/test_alpha9_baseline.py",
)
for relative in current_release_tests:
    path = ROOT / relative
    replace_once(
        path,
        'assert manifest["version"] == "0.9.0-alpha9.29"',
        'assert manifest["version"] == "0.9.0-alpha9.30"',
    )

# The gate now has a site-only mapping stage followed by the full battery mapping
# gate. Sustained telemetry evidence must still occur only after the active mapping
# gate is selected, and it must remain shadow/read-only.
gate = ROOT / "tests/test_commissioning_telemetry_gate.py"
replace_once(
    gate,
    '''        '"foxess_telemetry_mapping_gate_passed"',\n        "coordinator.settings.scan_interval_seconds",''',
    '''        '"foxess_telemetry_mapping_gate_passed"',\n        '"foxess_site_mapping_gate_passed"',\n        "commissioning_physical_mappings_ready",\n        "coordinator.settings.scan_interval_seconds",''',
)
replace_once(
    gate,
    '''    assert content.index("foxess_physical_mappings_ready = all(") < content.index(\n        "assess_foxess_telemetry_stability("\n    )''',
    '''    assert content.index("commissioning_physical_mappings_ready = (") < content.index(\n        "assess_foxess_telemetry_stability("\n    )''',
)

print("Alpha9.30 finalization applied successfully")
