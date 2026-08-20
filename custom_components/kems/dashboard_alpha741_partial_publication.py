"""Alpha7.41 dashboard visibility for progressive Agile price publication."""

from __future__ import annotations

_FORECAST_EVIDENCE = """            title: Forecast evidence
            show_header_toggle: false
            entities:
              - sensor.kems_forecast_solar_tomorrow
"""

_FORECAST_EVIDENCE_ALPHA741 = """            title: Forecast evidence
            show_header_toggle: false
            entities:
              - sensor.kems_agile_tomorrow_publication_plan
              - sensor.kems_forecast_solar_tomorrow
"""


def improve_alpha741_dashboard(content: str) -> str:
    """Put progressive tomorrow-price state beside the forecast evidence."""
    if "sensor.kems_agile_tomorrow_publication_plan" in content:
        return content
    if _FORECAST_EVIDENCE not in content:
        raise ValueError("Alpha7.41 Forecast evidence dashboard marker missing")
    return content.replace(
        _FORECAST_EVIDENCE,
        _FORECAST_EVIDENCE_ALPHA741,
        1,
    )


def install_alpha741_partial_publication_dashboard_patch() -> None:
    """Install Alpha7.41 dashboard addition after Alpha7.40 cards."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha741_partial_publication", False):
        return

    def combined_alpha741_dashboard() -> bytes:
        return improve_alpha741_dashboard(original().decode("utf-8")).encode("utf-8")

    combined_alpha741_dashboard._kems_alpha741_partial_publication = True
    dashboard_module._combined_master_dashboard_bytes = combined_alpha741_dashboard
