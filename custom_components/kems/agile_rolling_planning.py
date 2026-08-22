"""Canonical Agile rolling replanning and dashboard ownership.

This Alpha8 boundary retains the proven Alpha7.16 receding-horizon replanning,
live-history overlay and rolling-plan presentation without rewriting either
runtime. Frozen downstream runtimes import ``agile_rolling_replan`` by its
historical module name and patch that same module object, so a narrow
module-identity bridge keeps them pointed at the canonical byte-identical
runtime. The dashboard runtime is loaded only at its historical install
position. Real hardware writes remain blocked.
"""

from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType

from . import agile_rolling_replan_runtime as rolling_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Alpha7.17 and later frozen runtimes import and patch this historical module
# name, so preserve that shared object identity before any of them are loaded.
_bind_legacy_name("agile_rolling_replan", rolling_runtime)


def install_rolling_replan() -> None:
    """Install the proven Alpha7.16 rolling replanning layer."""
    rolling_runtime.install_rolling_replan_patch()


def install_rolling_dashboard() -> None:
    """Install the proven Alpha7.16 rolling-plan dashboard layer."""
    dashboard_runtime = import_module(
        ".agile_rolling_dashboard_runtime",
        __package__,
    )
    dashboard_runtime.install_alpha716_dashboard_patch()
