"""Canonical bounded partial-horizon dispatch ownership.

This Alpha8 boundary retains the proven Alpha7.28 bounded partial-horizon dispatch
without rewriting its upstream-gap verification, reserved-capacity guard, strict
non-zero proof, publication evidence, or hardware-write boundary. A narrow
legacy-name bridge keeps frozen downstream Alpha7.41 references on the same
canonical byte-identical runtime object.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_bounded_partial_runtime as bounded_partial_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Frozen Alpha7.41 imports Alpha7.28 by its historical name and patches
# _recovery_evidence. Keep that mutation on the canonical 7.28 runtime object.
_bind_legacy_name("agile_alpha728_bounded_partial", bounded_partial_runtime)


def install_bounded_partial_horizon() -> None:
    """Install the proven bounded partial-horizon dispatch behaviour."""
    bounded_partial_runtime.install_alpha728_bounded_partial_horizon_patch()
