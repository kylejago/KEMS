"""Single-Octopus source policy for KEMS with an Ohme ePod.

Bottlecapdave provides the contracted off-peak tariff, while Ohme provides
charger status/power. Neither official integration independently confirms
Ohme's extra daytime *whole-house* Intelligent discount dispatches. Never
create fictitious tariff authority from Ohme's planned charge slots.
"""

from __future__ import annotations

from collections.abc import Mapping

UNVERIFIED_OHME_EXTRA_SLOT_KEYS = frozenset(
    {"intelligent_slot", "next_offpeak_start", "offpeak_end"}
)


def consolidate_octopus_sources(mappings: Mapping[str, str]) -> dict[str, str]:
    """Retire unverified dispatch roles and preserve every other source."""
    return {
        key: value
        for key, value in mappings.items()
        if key not in UNVERIFIED_OHME_EXTRA_SLOT_KEYS
    }
