#!/usr/bin/env python3
"""Refresh current managed-panel contracts for Alpha9.28, then delete this file."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
OLD = "0.9.0-alpha9-panel.1"
NEW = "0.9.0-alpha9-panel.2"

changed = []
replacements = 0
for path in sorted(TESTS.glob("test_*.py")):
    text = path.read_text(encoding="utf-8")
    count = text.count(OLD)
    if not count:
        continue
    path.write_text(text.replace(OLD, NEW), encoding="utf-8")
    replacements += count
    changed.append((path.name, count))

assert 45 <= replacements <= 80, replacements

alpha926 = TESTS / "test_alpha926_panel_layout_profiles.py"
text = alpha926.read_text(encoding="utf-8")
expected = [
    "flow_vertical(4, 3, 5, 7",
    "flow_vertical(8, 3, 9, 7",
    "flow_vertical(12, 3, 13, 7",
    "flow_vertical(5, 10, 6, 14",
    "flow_vertical(11, 10, 12, 14",
]
for old in expected:
    assert text.count(old) == 1, old
    text = text.replace(old, old.replace("flow_vertical(", "flow_vertical_v2("), 1)
alpha926.write_text(text, encoding="utf-8")

print(f"Updated {replacements} panel.1 literals across {len(changed)} tests")
for name, count in changed:
    print(f"  {name}: {count}")
print("Updated five Alpha9.26 V2 geometry helper assertions")
