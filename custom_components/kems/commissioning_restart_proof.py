"""Restart-safe certificate for previously proven FoxESS commissioning evidence.

Raw physical commissioning samples remain session-scoped. This store retains only
an identity-bound certificate that the preceding session completed the temporal
FoxESS proof. The certificate can bridge WAIT-only recollection after restart; it
must never override a current mapping, unit, sign, telemetry, or safety failure.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE

_STORAGE_VERSION = 1
_CERTIFICATE_VERSION = 1


def _normalise_signature(value: Any) -> list[dict[str, str | None]] | None:
    """Return one stable JSON-safe source signature."""
    if not isinstance(value, (list, tuple)):
        return None

    result: list[dict[str, str | None]] = []
    for item in value:
        if isinstance(item, Mapping):
            role = item.get("role")
            identity = item.get("identity")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            role, identity = item
        else:
            return None
        if not role:
            return None
        result.append(
            {
                "role": str(role),
                "identity": str(identity) if identity is not None else None,
            }
        )
    return result


def restart_proof_matches(
    proof: Mapping[str, Any] | None,
    *,
    source_signature: Any,
    direction_source_signature: Any,
    configured_positive_is_discharge: bool,
) -> bool:
    """Return whether persisted proof exactly matches the current physical contract."""
    if not isinstance(proof, Mapping):
        return False
    if proof.get("certificate_version") != _CERTIFICATE_VERSION:
        return False

    source = _normalise_signature(source_signature)
    direction = _normalise_signature(direction_source_signature)
    stored_source = _normalise_signature(proof.get("source_signature"))
    stored_direction = _normalise_signature(proof.get("direction_source_signature"))
    if source is None or direction is None:
        return False
    if stored_source != source or stored_direction != direction:
        return False
    if "configured_positive_is_discharge" not in proof:
        return False
    return bool(proof["configured_positive_is_discharge"]) == bool(
        configured_positive_is_discharge
    )


class CommissioningRestartProof:
    """Persist only the identity of a fully proven FoxESS commissioning session."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._store = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.commissioning_restart_proof",
        )
        self._proof: dict[str, Any] | None = None

    @property
    def proof(self) -> dict[str, Any] | None:
        """Return the loaded certificate without exposing mutable internal state."""
        return dict(self._proof) if isinstance(self._proof, dict) else None

    async def async_load(self) -> None:
        """Load one previously proven certificate, if structurally usable."""
        data = await self._store.async_load()
        if (
            isinstance(data, dict)
            and data.get("certificate_version") == _CERTIFICATE_VERSION
            and _normalise_signature(data.get("source_signature")) is not None
            and _normalise_signature(data.get("direction_source_signature")) is not None
        ):
            self._proof = dict(data)
        else:
            self._proof = None

    async def async_capture(self, commissioning: Mapping[str, Any]) -> bool:
        """Persist a certificate only from fresh, fully proven physical evidence."""
        if not bool(commissioning.get("fresh_foxess_telemetry_proof_ready")):
            return False

        session = commissioning.get("foxess_commissioning_session")
        direction_session = commissioning.get("foxess_battery_direction_session")
        if not isinstance(session, Mapping) or not isinstance(
            direction_session, Mapping
        ):
            return False

        source_signature = _normalise_signature(session.get("source_signature"))
        direction_signature = _normalise_signature(
            direction_session.get("source_signature")
        )
        if source_signature is None or direction_signature is None:
            return False

        identity = {
            "certificate_version": _CERTIFICATE_VERSION,
            "source_signature": source_signature,
            "direction_source_signature": direction_signature,
            "configured_positive_is_discharge": bool(
                commissioning.get("configured_battery_power_positive_is_discharge")
            ),
        }
        current = self._proof or {}
        if all(current.get(key) == value for key, value in identity.items()):
            return False

        certificate = {
            **identity,
            "verified_at": datetime.now(UTC).isoformat(),
        }
        await self._store.async_save(certificate)
        self._proof = certificate
        return True
