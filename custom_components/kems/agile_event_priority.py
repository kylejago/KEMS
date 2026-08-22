"""Canonical installer for Agile Power Down and Happy Hour event priority.

Alpha8 owns the proven event-priority behavior through a non-versioned runtime
surface.  The runtime implementation remains byte-identical to the validated
Alpha7.43 behavior in this parity slice; this facade only gives the executable
compatibility registry a canonical installer name.

Real FoxESS hardware writes remain blocked by the underlying runtime contract.
"""

from __future__ import annotations

from . import agile_event_priority_runtime as event_runtime


def install_event_priority() -> None:
    """Install proven Power Down and Weekend Happy Hour priority behavior."""
    event_runtime.install_alpha743_event_priority_patch()
