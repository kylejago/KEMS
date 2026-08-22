"""Canonical non-zero export proof and provisional-planning ownership.

This Alpha8 boundary retains the proven Alpha7.25 non-zero shadow proof and
Alpha7.26 provisional economic planning without rewriting either runtime. A
narrow import-name bridge keeps the frozen Alpha7.27 recovery and Alpha7.28
bounded-partial dependencies pointed at these canonical byte-identical module
objects. Real hardware writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_nonzero_export_proof_runtime as nonzero_runtime
from . import agile_provisional_planning_runtime as provisional_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Alpha7.28 imports the Alpha7.25 replay helpers by the historical module name.
# Keep that frozen dependency on the canonical byte-identical runtime object.
_bind_legacy_name("agile_alpha725_nonzero", nonzero_runtime)

# Alpha7.27 imports Alpha7.26 by its historical name and calls installer-populated
# module globals such as alpha726_original_fetch_rates. Alpha7.28 also imports its
# reserve helper. Both dependencies therefore require the exact canonical 7.26
# module object rather than a separately imported historical copy.
_bind_legacy_name("agile_alpha726_provisional", provisional_runtime)


def install_nonzero_export_proof() -> None:
    """Install the proven Alpha7.25 non-zero export shadow proof."""
    nonzero_runtime.install_alpha725_nonzero_export_proof_patch()


def install_provisional_planning() -> None:
    """Install the proven Alpha7.26 provisional planning layer."""
    provisional_runtime.install_alpha726_provisional_planning_patch()
