from pathlib import Path

panel = Path("custom_components/kems/kems16x16.yaml")
text = panel.read_text(encoding="utf-8")
if "\nglobals:\n" not in text:
    block = '''globals:\n  - id: panel_boot_started_ms\n    type: uint32_t\n    restore_value: no\n    initial_value: '0'\n  - id: panel_boot_ha_seen\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n  - id: panel_boot_ha_ready_ms\n    type: uint32_t\n    restore_value: no\n    initial_value: '0'\n\n'''
    text = text.replace("captive_portal:\nselect:\n", "captive_portal:\n" + block + "select:\n", 1)
    panel.write_text(text, encoding="utf-8")
