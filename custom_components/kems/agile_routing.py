"""Canonical current-routing and solar-headroom ownership.

This Alpha8 boundary retains the proven Alpha7.30 current-routing snapshot and
Alpha7.31 solar-aware shared-inverter behaviour without rewriting either runtime.
A narrow import-name bridge keeps their frozen cross-module references pointed at
the canonical byte-identical module objects, including the Alpha7.34 deadline
helper dependency. Real hardware writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_current_routing_runtime as current_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Alpha7.31 imports Alpha7.30 by its historical module name and patches _snapshot
# plus _CURRENT_ROUTING_CARD. Bind that name before importing the unchanged 7.31
# runtime so the patch lands on the canonical 7.30 object rather than a duplicate.
_bind_legacy_name("agile_alpha730_current_routing", current_runtime)

from . import agile_solar_headroom_runtime as solar_runtime  # noqa: E402

# Alpha7.34 imports the Alpha7.31 helper by its historical module name. Binding
# the name here lets the byte-identical canonical deadline runtime resolve the
# helper from the canonical 7.31 object without editing either frozen runtime.
_bind_legacy_name("agile_alpha731_solar_headroom", solar_runtime)


def install_current_routing() -> None:
    """Install the proven coherent current-routing snapshot."""
    current_runtime.install_alpha730_current_routing_patch()


def install_solar_headroom() -> None:
    """Install the proven solar-aware inverter-headroom routing layer."""
    solar_runtime.install_alpha731_solar_headroom_patch()
