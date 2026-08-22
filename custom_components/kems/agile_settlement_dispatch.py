"""Canonical Agile settlement-slot dispatch and dashboard ownership.

This Alpha8 boundary retains the proven Alpha7.17 deadline-saturation dispatch,
current-slot target publication and dashboard presentation without rewriting
either runtime. Frozen downstream runtimes import ``agile_alpha717_dispatch`` by
its historical module name, so a narrow module-identity bridge keeps them
pointed at the canonical byte-identical dispatch runtime. The dashboard runtime
is loaded only at its historical install position. Real hardware writes remain
blocked.
"""

from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType

from . import agile_settlement_dispatch_runtime as dispatch_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Frozen downstream runtimes import and call this historical module name, so
# preserve that shared object identity before any of them are loaded.
_bind_legacy_name("agile_alpha717_dispatch", dispatch_runtime)


def install_settlement_dispatch() -> None:
    """Install the proven Alpha7.17 settlement-slot dispatch layer."""
    dispatch_runtime.install_alpha717_dispatch_patch()


def install_settlement_dispatch_dashboard() -> None:
    """Install the proven Alpha7.17 dispatch dashboard layer."""
    dashboard_runtime = import_module(
        ".agile_settlement_dispatch_dashboard_runtime",
        __package__,
    )
    dashboard_runtime.install_alpha717_dashboard_patch()
