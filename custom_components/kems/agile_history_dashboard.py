"""Canonical Agile deadline/history dashboard presentation ownership.

This Alpha8 boundary retains the proven Alpha7.14 deadline, hardware-SOC and
historical-backfill presentation plus the Alpha7.15 sensor-backed diagnostics
replacement without rewriting either runtime. The frozen Alpha7.15 runtime
imports Alpha7.14 by its historical module name solely to reuse the original
Markdown card constant, so a narrow module-identity bridge is installed before
that runtime is imported. Real hardware writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_deadline_history_dashboard_runtime as deadline_history_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# The exact Alpha7.15 dashboard runtime imports Alpha7.14 by historical name and
# reads _BACKFILL_DIAGNOSTICS_CARD from that module object.
_bind_legacy_name("agile_alpha714_dashboard", deadline_history_runtime)

from . import agile_history_diagnostics_dashboard_runtime as diagnostics_runtime  # noqa: E402


def install_deadline_history_dashboard() -> None:
    """Install the proven Alpha7.14 deadline/history presentation layer."""
    deadline_history_runtime.install_alpha714_dashboard_patch()


def install_history_diagnostics_dashboard() -> None:
    """Install the proven Alpha7.15 sensor-backed diagnostics presentation."""
    diagnostics_runtime.install_alpha715_dashboard_patch()
