#!/usr/bin/env python3
"""Render the runtime-managed ESPHome payload for CI validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
OUTPUT = ROOT / "custom_components" / "kems" / "kems16x16-ci.yaml"
MODULE = ROOT / "custom_components" / "kems" / "panel_ev_policy.py"

spec = importlib.util.spec_from_file_location("kems_panel_ev_policy", MODULE)
assert spec is not None and spec.loader is not None
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

OUTPUT.write_text(
    policy.apply_ev_policy_panel(SOURCE.read_text(encoding="utf-8")), encoding="utf-8"
)
print(OUTPUT)
