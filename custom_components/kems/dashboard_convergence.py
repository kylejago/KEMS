"""Deterministic managed-dashboard convergence helpers.

This module is intentionally Home Assistant independent so the exact file repair and
verification behaviour can be exercised by the normal pytest suite.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class DashboardConvergenceError(RuntimeError):
    """Raised when the managed dashboard cannot be repaired exactly."""


@dataclass(frozen=True, slots=True)
class DashboardVerification:
    """Exact-byte verification result for one managed dashboard file."""

    current: bool
    target: str
    expected_sha256: str
    installed_sha256: str | None
    detail: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_managed_dashboard(
    target: Path,
    expected: bytes,
) -> DashboardVerification:
    """Compare the installed dashboard with the exact generated payload."""
    expected_sha256 = _sha256(expected)
    try:
        installed = target.read_bytes()
    except FileNotFoundError:
        return DashboardVerification(
            current=False,
            target=str(target),
            expected_sha256=expected_sha256,
            installed_sha256=None,
            detail=(
                f"Managed dashboard is missing at {target}; "
                f"expected_sha256={expected_sha256}"
            ),
        )
    except OSError as error:
        return DashboardVerification(
            current=False,
            target=str(target),
            expected_sha256=expected_sha256,
            installed_sha256=None,
            detail=(
                f"Managed dashboard could not be read at {target}: {error}; "
                f"expected_sha256={expected_sha256}"
            ),
        )

    installed_sha256 = _sha256(installed)
    if installed == expected:
        detail = (
            f"Managed dashboard hash matches generated YAML at {target}; "
            f"sha256={expected_sha256}"
        )
    else:
        detail = (
            f"Managed dashboard hash mismatch at {target}; "
            f"expected_sha256={expected_sha256}; "
            f"installed_sha256={installed_sha256}"
        )
    return DashboardVerification(
        current=installed == expected,
        target=str(target),
        expected_sha256=expected_sha256,
        installed_sha256=installed_sha256,
        detail=detail,
    )


def sync_and_verify_managed_dashboard(
    target: Path,
    expected: bytes,
) -> DashboardVerification:
    """Atomically repair the managed dashboard and prove the exact bytes landed."""
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        installed = target.read_bytes() if target.exists() else None
        if installed != expected:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(expected)
            os.replace(temporary, target)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DashboardConvergenceError(
            f"Managed dashboard repair failed at {target}: {error}"
        ) from error

    verification = verify_managed_dashboard(target, expected)
    if not verification.current:
        raise DashboardConvergenceError(verification.detail)
    return verification
