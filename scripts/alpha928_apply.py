#!/usr/bin/env python3
"""Temporary guarded Alpha9.28 panel migration. Delete after use."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
PANEL_HEALTH = ROOT / "custom_components" / "kems" / "panel.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
TESTS = ROOT / "tests"

panel = PANEL.read_text(encoding="utf-8")
old_panel_version = 'panel_config_version: "0.9.0-alpha9-panel.1"'
new_panel_version = 'panel_config_version: "0.9.0-alpha9-panel.2"'
assert panel.count(old_panel_version) == 1
panel = panel.replace(old_panel_version, new_panel_version, 1)

marker = "      auto bool_colour = [&](bool value) -> Color {\n"
assert panel.count(marker) == 1
assert "auto flow_vertical_v2_dual" not in panel
helper = """      // V2 uses five-row connectors. Start the next packet when the
      // prior head reaches the fourth position so the longer path stays fluid.
      auto flow_vertical_v2_dual = [&](int c1, int r1, int c2, int r2,
                                       Color head_left, Color head_right,
                                       Color trail_left, Color trail_right,
                                       int dir) {
        rect(c1, r1, c2, r2, OFF);
        const int height = r2 - r1 + 1;
        const int launch_spacing = 3;
        const int phase = (now / 450) % launch_spacing;
        auto physical_index = [&](int travel_index) -> int {
          return (dir > 0)
            ? travel_index
            : (height - 1 - travel_index);
        };
        auto draw_packet = [&](int head) {
          if (head >= 0 && head < height) {
            int index = physical_index(head);
            vertical_pair(
              r1 + index, c1, c2,
              head_left, head_right,
              1.00f
            );
          }
          int age1 = head - 1;
          if (age1 >= 0 && age1 < height) {
            int index = physical_index(age1);
            vertical_pair(
              r1 + index, c1, c2,
              trail_left, trail_right,
              0.66f
            );
          }
          int age2 = head - 2;
          if (age2 >= 0 && age2 < height) {
            int index = physical_index(age2);
            vertical_pair(
              r1 + index, c1, c2,
              trail_left, trail_right,
              0.33f
            );
          }
        };
        for (int head = phase; head < height + 2; head += launch_spacing) {
          draw_packet(head);
        }
      };
      auto flow_vertical_v2 = [&](int c1, int r1, int c2, int r2,
                                  Color left_color, Color right_color,
                                  int dir) {
        flow_vertical_v2_dual(
          c1, r1, c2, r2,
          left_color, right_color,
          left_color, right_color,
          dir
        );
      };
"""
panel = panel.replace(marker, helper + marker, 1)

v2_start = panel.index("      if (layout_v2) {")
v2_end = panel.index("        return;\n      }", v2_start)
v2 = panel[v2_start:v2_end]
assert v2.count("flow_vertical(") >= 5
assert v2.count("flow_vertical_dual(") >= 2
v2 = v2.replace("flow_vertical_dual(", "flow_vertical_v2_dual(")
v2 = v2.replace("flow_vertical(", "flow_vertical_v2(")
panel = panel[:v2_start] + v2 + panel[v2_end:]
PANEL.write_text(panel, encoding="utf-8")

panel_health = PANEL_HEALTH.read_text(encoding="utf-8")
old_health = 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.1"'
new_health = 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.2"'
assert panel_health.count(old_health) == 1
PANEL_HEALTH.write_text(panel_health.replace(old_health, new_health, 1), encoding="utf-8")

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
assert manifest["version"] == "0.9.0-alpha9.27"
manifest["version"] = "0.9.0-alpha9.28"
MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.1"
bundle["components"]["panel"]["version"] = "0.9.0-alpha9-panel.2"
reason = str(bundle["maintenance"]["reason"])
prefix = (
    "Alpha9.28 advances the managed panel to 0.9.0-alpha9-panel.2 with a "
    "V2-only staggered-flow animation. Each five-row V2 connector launches "
    "the next flow packet when the preceding head reaches the fourth position, "
    "while V1 keeps its established 2x4 flow timing unchanged. "
)
assert reason.startswith("Alpha9 coordinated parity baseline; ")
reason = reason.replace(
    "Alpha9 coordinated parity baseline; ",
    "Alpha9 coordinated parity baseline; " + prefix,
    1,
)
assert "Panel remains 0.9.0-alpha9-panel.1" in reason
reason = reason.replace(
    "Panel remains 0.9.0-alpha9-panel.1",
    "Panel advances to 0.9.0-alpha9-panel.2",
    1,
)
bundle["maintenance"]["reason"] = reason
BUNDLE.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

old_manifest_assert = 'assert manifest["version"] == "0.9.0-alpha9.27"'
new_manifest_assert = 'assert manifest["version"] == "0.9.0-alpha9.28"'
changed: list[str] = []
for path in sorted(TESTS.glob("test_*.py")):
    if path.name == "test_alpha928_panel_v2_staggered_flow.py":
        continue
    text = path.read_text(encoding="utf-8")
    count = text.count(old_manifest_assert)
    if count:
        assert count == 1, (path, count)
        path.write_text(text.replace(old_manifest_assert, new_manifest_assert, 1), encoding="utf-8")
        changed.append(path.name)
assert 8 <= len(changed) <= 20, changed
print("Advanced current-release manifest assertions:", ", ".join(changed))

alpha926 = TESTS / "test_alpha926_panel_layout_profiles.py"
text = alpha926.read_text(encoding="utf-8")
assert text.count("0.9.0-alpha9-panel.1") == 3
alpha926.write_text(text.replace("0.9.0-alpha9-panel.1", "0.9.0-alpha9-panel.2"), encoding="utf-8")

print("Alpha9.28 guarded migration applied")
