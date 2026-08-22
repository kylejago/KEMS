"""Canonical observable Agile price-recovery ownership.

This Alpha8 boundary retains the proven Alpha7.27 exact-slot and context-window
recovery behaviour without rewriting its Octopus-gap classification, diagnostic
evidence, failure handling, or Alpha7.26 compatibility state. Alpha7.28 continues
to consume the published diagnostic state without depending on this module name.
Real hardware writes remain blocked.
"""

from __future__ import annotations

from . import agile_price_recovery_runtime as price_recovery_runtime


def install_price_recovery() -> None:
    """Install the proven observable Agile missing-price recovery."""
    price_recovery_runtime.install_alpha727_price_recovery_patch()
