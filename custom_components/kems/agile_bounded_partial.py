"""Canonical bounded partial-horizon dispatch ownership.

This Alpha8 boundary retains the proven Alpha7.28 bounded partial-horizon dispatch
without rewriting its upstream-gap verification, reserved-capacity guard, strict
non-zero proof, publication evidence, or hardware-write boundary.
"""

from __future__ import annotations

from . import agile_bounded_partial_runtime as bounded_partial_runtime


def install_bounded_partial_horizon() -> None:
    """Install the proven bounded partial-horizon dispatch behaviour."""
    bounded_partial_runtime.install_alpha728_bounded_partial_horizon_patch()
