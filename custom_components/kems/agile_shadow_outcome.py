"""Canonical Agile shadow-command and outcome-parity ownership.

This Alpha8 boundary retains the proven Alpha7.23 shadow-command parity and
Alpha7.24 routed outcome-parity behaviour without rewriting either runtime. A
narrow import-name bridge keeps frozen downstream runtimes pointed at these
canonical byte-identical module objects. Real hardware writes remain blocked.
"""

from __future__ import annotations

import sys
from types import ModuleType

from . import agile_shadow_command_runtime as shadow_runtime

_PACKAGE = sys.modules[__package__]


def _bind_legacy_name(name: str, module: ModuleType) -> None:
    """Bind one frozen historical import name to its canonical runtime object."""
    qualified = f"{__package__}.{name}"
    sys.modules[qualified] = module
    setattr(_PACKAGE, name, module)


# Alpha7.24 imports Alpha7.23 by its historical name, captures its original
# build/evaluate/record functions, then patches that module object in place.
_bind_legacy_name("agile_alpha723_shadow", shadow_runtime)

from . import agile_outcome_parity_runtime as outcome_runtime  # noqa: E402

# Alpha7.25 imports both Alpha7.23 and Alpha7.24 by their historical names.
# Later Alpha7.28 and Alpha7.31 also patch the same Alpha7.23 object.
_bind_legacy_name("agile_alpha724_outcome", outcome_runtime)


def install_shadow_command() -> None:
    """Install the proven Alpha7.23 Agile shadow-command parity layer."""
    shadow_runtime.install_alpha723_shadow_patch()


def install_outcome_parity() -> None:
    """Install the proven Alpha7.24 routed outcome-parity layer."""
    outcome_runtime.install_alpha724_outcome_parity_patch()
