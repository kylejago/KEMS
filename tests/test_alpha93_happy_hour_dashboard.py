"""Alpha9.3 managed-dashboard Happy Hour restoration contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboards/kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components/kems/kems_master_dashboard.yaml"


def test_alpha93_restores_all_happy_hour_controls_to_system_dashboard() -> None:
    content = SOURCE.read_text(encoding="utf-8")
    for entity in (
        "switch.kems_weekend_happy_hour_planning",
        "datetime.kems_weekend_happy_hour_start",
        "select.kems_weekend_happy_hour_duration",
        "switch.kems_happy_hour_ohme_control",
    ):
        assert entity in content
    assert "16 kWh per reward hour" in content
    assert "Unused allowance never carries forward" in content
    assert "normal tariff logic resumes" in content
    assert "Ohme control is opt-in" in content


def test_alpha93_packaged_dashboard_matches_source() -> None:
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()
