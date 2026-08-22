"""Canonical Agile price-publication compatibility boundary.

This Alpha8 facade owns the proven Alpha7.41 progressive publication behavior
without keeping the version-named modules in the executable compatibility
registry. The runtime and dashboard owners remain byte-identical to the
historical implementations in this parity slice. A narrow legacy-name bridge
keeps later publication reporting on the canonical price-publication runtime.

Known prices may be used only through the existing bounded partial-horizon
safety rules; unpublished prices are never guessed, unknown-slot discharge
capacity remains fully reserved, and real FoxESS hardware writes remain
blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_price_publication_runtime as price_runtime
from . import dashboard_price_publication_runtime as dashboard_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Canonical publication reporting still references Alpha7.41's historical module
# name. Keep its _progressive_tomorrow_state mutation on the canonical runtime.
_bind_legacy_name("agile_alpha741_partial_publication", price_runtime)


def install_price_publication() -> None:
    """Install price-publication behavior in the proven Alpha7.41 order."""
    price_runtime.install_alpha741_partial_publication_patch()
    dashboard_runtime.install_alpha741_partial_publication_dashboard_patch()
