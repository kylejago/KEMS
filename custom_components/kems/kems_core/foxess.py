"""Home Assistant-independent FoxESS and grid-flow calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GridPower:
    """Normalised grid power and the rule used to derive it."""

    import_kw: float | None
    export_kw: float | None
    raw_import_kw: float | None
    raw_export_kw: float | None
    mode: str


def calculate_battery_power_kw(
    voltage: float | None,
    current: float | None,
) -> float | None:
    """Calculate battery power from FoxESS voltage and current sensors."""
    if voltage is None or current is None:
        return None
    return round(voltage * current / 1000, 3)


def normalise_grid_power(
    raw_import_kw: float | None,
    raw_export_kw: float | None,
) -> GridPower:
    """Normalise separate or signed grid readings into positive import/export.

    KEMS always exposes import and export as non-negative magnitudes. The signed
    net entity is calculated later as import minus export. This helper also
    protects against one signed source being mapped into both fields.
    """
    if raw_import_kw is None and raw_export_kw is None:
        return GridPower(None, None, None, None, "no_grid_source")

    if raw_import_kw is not None and raw_export_kw is not None:
        if abs(raw_import_kw - raw_export_kw) < 0.0005:
            if raw_import_kw >= 0:
                return GridPower(
                    round(raw_import_kw, 3),
                    0.0,
                    raw_import_kw,
                    raw_export_kw,
                    "duplicate_signed_source_import",
                )
            return GridPower(
                0.0,
                round(abs(raw_import_kw), 3),
                raw_import_kw,
                raw_export_kw,
                "duplicate_signed_source_export",
            )

        if raw_import_kw < 0 <= raw_export_kw:
            return GridPower(
                0.0,
                round(max(abs(raw_import_kw), raw_export_kw), 3),
                raw_import_kw,
                raw_export_kw,
                "signed_import_source_exporting",
            )
        if raw_export_kw < 0 <= raw_import_kw:
            return GridPower(
                round(max(raw_import_kw, abs(raw_export_kw)), 3),
                0.0,
                raw_import_kw,
                raw_export_kw,
                "signed_export_source_importing",
            )

        return GridPower(
            round(max(raw_import_kw, 0.0), 3),
            round(max(raw_export_kw, 0.0), 3),
            raw_import_kw,
            raw_export_kw,
            "separate_positive_sources",
        )

    if raw_import_kw is not None:
        if raw_import_kw >= 0:
            return GridPower(
                round(raw_import_kw, 3),
                0.0,
                raw_import_kw,
                None,
                "single_import_source",
            )
        return GridPower(
            0.0,
            round(abs(raw_import_kw), 3),
            raw_import_kw,
            None,
            "single_signed_source_exporting",
        )

    assert raw_export_kw is not None
    if raw_export_kw >= 0:
        return GridPower(
            0.0,
            round(raw_export_kw, 3),
            None,
            raw_export_kw,
            "single_export_source",
        )
    return GridPower(
        round(abs(raw_export_kw), 3),
        0.0,
        None,
        raw_export_kw,
        "single_signed_source_importing",
    )
