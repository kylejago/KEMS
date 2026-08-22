"""Canonical Agile price-horizon safety ownership.

This Alpha8 boundary retains the proven Alpha7.22 price-horizon readiness and
battery-export safety behaviour without rewriting its runtime. A narrow
import-name bridge keeps frozen Alpha7.26 provisional planning pointed at the
canonical byte-identical module object. Real hardware writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_price_horizon_safety_runtime as price_horizon_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Frozen Alpha7.26 imports Alpha7.22 by its historical module name, captures the
# hold helper, and replaces that helper in place with provisional-plan evidence.
_bind_legacy_name("agile_alpha722_horizon", price_horizon_runtime)


def install_price_horizon_safety() -> None:
    """Install the proven Alpha7.22 Agile price-horizon safety behaviour."""
    price_horizon_runtime.install_alpha722_price_horizon_patch()
