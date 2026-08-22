"""Canonical Agile price-publication compatibility boundary.

This Alpha8 facade owns the proven Alpha7.41 progressive publication behavior
without keeping the version-named modules in the executable compatibility
registry. The runtime and dashboard owners remain byte-identical to the
historical implementations in this parity slice.

Known prices may be used only through the existing bounded partial-horizon
safety rules; unpublished prices are never guessed, unknown-slot discharge
capacity remains fully reserved, and real FoxESS hardware writes remain
blocked.
"""

from __future__ import annotations

from . import agile_price_publication_runtime as price_runtime
from . import dashboard_price_publication_runtime as dashboard_runtime


def install_price_publication() -> None:
    """Install price-publication behavior in the proven Alpha7.41 order."""
    price_runtime.install_alpha741_partial_publication_patch()
    dashboard_runtime.install_alpha741_partial_publication_dashboard_patch()
