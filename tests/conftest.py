"""Test configuration for the Home Assistant-independent KEMS core."""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "kems"
sys.path.insert(0, str(INTEGRATION_DIR))
