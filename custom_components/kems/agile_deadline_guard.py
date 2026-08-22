"""Canonical latest-safe-start deadline guard ownership.

This Alpha8 boundary retains the proven Alpha7.34 deadline/dispatch behaviour
without rewriting its solar-aware shared-inverter capacity model, escalation
policy, or historical Alpha7.31/Alpha7.17 dependencies. A narrow legacy-name
bridge keeps later deadline-plan reconciliation on the same canonical
byte-identical runtime object. Real hardware writes remain blocked behind the
existing commissioning and backend gates.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_deadline_guard_runtime as deadline_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Canonical deadline-plan reconciliation still references the frozen Alpha7.34
# module name. Keep its helper reads and mutations on the canonical runtime.
_bind_legacy_name("agile_alpha734_deadline_guard", deadline_runtime)


def install_deadline_guard() -> None:
    """Install the proven latest-safe-start deadline guard."""
    deadline_runtime.install_alpha734_deadline_guard_patch()
