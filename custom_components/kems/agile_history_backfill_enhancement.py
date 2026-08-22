"""Canonical enhanced Agile historical-backfill ownership.

This Alpha8 boundary retains the proven Energy-dashboard fallback and historical
source diagnostics without rewriting the runtime body. A narrow legacy-name
bridge keeps the frozen Alpha7.15 compatibility runtime pointed at the same
byte-identical module object before it patches ``_energy_sources``. Real hardware
writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_history_backfill_enhancement_runtime as enhancement_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


_bind_legacy_name("agile_history_backfill_v2", enhancement_runtime)


def install_history_backfill_enhancement() -> None:
    """Install the proven enhanced historical-backfill layer."""
    enhancement_runtime.install_enhanced_backfill()
