"""Canonical Agile validation evidence and dashboard ownership.

This Alpha8 boundary retains the proven Alpha7.19 evidence gating, SOC trajectory,
decision audit, historical-source proof, and validation dashboard without rewriting
either runtime. Narrow historical-name bridges keep frozen Alpha7.26 provisional
planning pointed at the canonical byte-identical module objects. Real hardware
writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_validation_dashboard_runtime as dashboard_runtime
from . import agile_validation_evidence_runtime as validation_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Frozen Alpha7.26 imports both Alpha7.19 modules by their historical names. It
# replaces validation helpers in place and updates the dashboard card payload, so
# both names must resolve to the canonical byte-identical module objects.
_bind_legacy_name("agile_alpha719_validation", validation_runtime)
_bind_legacy_name("agile_alpha719_dashboard", dashboard_runtime)


def install_validation_evidence() -> None:
    """Install the proven Alpha7.19 validation and evidence behaviour."""
    validation_runtime.install_alpha719_validation_patch()


def install_validation_dashboard() -> None:
    """Install the proven Alpha7.19 validation dashboard behaviour."""
    dashboard_runtime.install_alpha719_dashboard_patch()
