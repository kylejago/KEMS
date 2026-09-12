from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: Path, old: str, new: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} occurrences of {old!r}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


panel = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
replace_exact(
    panel,
    'panel_config_version: "0.9.0-alpha9-panel.2"',
    'panel_config_version: "0.9.0-alpha9-panel.3"',
)
replace_exact(
    panel,
    "// V2 uses five-row connectors. Start the next packet when the\n"
    "      // prior head reaches the fourth position so the longer path stays fluid.",
    "// V2 uses five-row connectors. Four-position launch spacing leaves\n"
    "      // one dark row between packets so opposing flows are easier to read.",
)
replace_exact(panel, "const int launch_spacing = 3;", "const int launch_spacing = 4;")

manifest = ROOT / "custom_components" / "kems" / "manifest.json"
replace_exact(manifest, '"version": "0.9.0-alpha9.28"', '"version": "0.9.0-alpha9.29"')

panel_health = ROOT / "custom_components" / "kems" / "panel.py"
replace_exact(
    panel_health,
    'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.2"',
    'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.3"',
)

bundle = ROOT / "release" / "kems-bundle.template.json"
replace_exact(
    bundle,
    '"version": "0.9.0-alpha9-panel.2"',
    '"version": "0.9.0-alpha9-panel.3"',
)
replace_exact(
    bundle,
    "Alpha9 coordinated parity baseline; Alpha9.28 advances",
    "Alpha9 coordinated parity baseline; Alpha9.29 adds one extra gap to the V2 flow animation: four-position packet spacing leaves one dark row between packets so simultaneous import and export directions are easier to distinguish, while V1 remains unchanged. Alpha9.28 advances",
)
replace_exact(
    bundle,
    "Panel advances to 0.9.0-alpha9-panel.2;",
    "Panel advances to 0.9.0-alpha9-panel.3;",
)

# Alpha9.28 introduced the V2 stagger helper. Its historical regression should
# keep proving the helper/geometry exists without freezing the exact spacing,
# which Alpha9.29 intentionally refines.
alpha928 = ROOT / "tests" / "test_alpha928_panel_v2_staggered_flow.py"
replace_exact(
    alpha928,
    '    assert "const int launch_spacing = 3;" in panel\n    assert "prior head reaches the fourth position" in panel',
    '    assert "const int launch_spacing =" in panel\n    assert "flow_vertical_v2_dual" in panel',
)

# Refresh the established current-release/current-panel assertions. These are
# deliberately literal successor contracts across the regression suite.
core_updates = 0
panel_updates = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new = text.replace('"0.9.0-alpha9.28"', '"0.9.0-alpha9.29"')
    core_updates += text.count('"0.9.0-alpha9.28"')
    text = new
    new = text.replace('"0.9.0-alpha9-panel.2"', '"0.9.0-alpha9-panel.3"')
    panel_updates += text.count('"0.9.0-alpha9-panel.2"')
    if new != path.read_text(encoding="utf-8"):
        path.write_text(new, encoding="utf-8")

if core_updates < 1:
    raise RuntimeError("No Alpha9.28 successor-version test literals were refreshed")
if panel_updates < 1:
    raise RuntimeError("No panel.2 successor-version test literals were refreshed")

print(f"refreshed core literals: {core_updates}")
print(f"refreshed panel literals: {panel_updates}")
