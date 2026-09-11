from __future__ import annotations

from pathlib import Path

TESTS = Path("tests")

panel_old = "0.9.0-alpha9-panel.0"
panel_new = "0.9.0-alpha9-panel.1"
core_old = "0.9.0-alpha9.25"
core_new = "0.9.0-alpha9.26"

panel_replacements = 0
core_replacements = 0

for path in sorted(TESTS.rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    panel_count = text.count(panel_old)
    core_count = text.count(core_old)
    if panel_count or core_count:
        text = text.replace(panel_old, panel_new).replace(core_old, core_new)
        path.write_text(text, encoding="utf-8")
        panel_replacements += panel_count
        core_replacements += core_count

profile = TESTS / "test_alpha926_panel_layout_profiles.py"
text = profile.read_text(encoding="utf-8")
old = '''    assert "KEMSPanelLayoutSelect" in select\n    assert '\"V1 — Current\"' in select\n    assert '\"V2 — Inverter centred\"' in select\n    assert "select.kems_panel_layout" in dashboard\n'''
new = '''    assert "KEMSPanelLayoutSelect" in select\n    assert '\"V1 — Current\"' in const\n    assert '\"V2 — Inverter centred\"' in const\n    assert "select.kems_panel_layout" in dashboard\n'''
if text.count(old) != 1:
    raise SystemExit("Alpha9.26 profile label assertion marker was not unique")
profile.write_text(text.replace(old, new, 1), encoding="utf-8")

if panel_replacements < 40:
    raise SystemExit(f"Expected broad panel successor migration, got {panel_replacements}")
if core_replacements < 8:
    raise SystemExit(f"Expected current-core successor migration, got {core_replacements}")

print(
    f"Updated {panel_replacements} panel-version assertions and "
    f"{core_replacements} current-core assertions."
)
