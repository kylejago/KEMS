"""Test configuration for the Home Assistant-independent KEMS core."""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "kems"

# Keep the standard library ahead of KEMS platform modules such as select.py.
sys.path.append(str(INTEGRATION_DIR))
