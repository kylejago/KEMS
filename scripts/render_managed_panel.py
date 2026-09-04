#!/usr/bin/env python3
"""Render the packaged managed ESPHome payload for CI validation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
OUTPUT = ROOT / "custom_components" / "kems" / "kems16x16-ci.yaml"

OUTPUT.write_bytes(SOURCE.read_bytes())
print(OUTPUT)
