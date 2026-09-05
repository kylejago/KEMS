"""Alpha9 coordinated parity baseline contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_alpha9_four_track_versions_are_explicit() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release/kems-bundle.template.json").read_text(encoding="utf-8")
    )

    assert manifest["version"] == "0.9.0-alpha9.2"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["public_web"]["version"] == ("0.9.0-alpha9-public.0")


def test_alpha9_does_not_start_a_version_named_patch_chain() -> None:
    assert sorted(path.name for path in KEMS.glob("agile_alpha9*.py")) == []


def test_alpha9_foxess_write_boundary_remains_closed() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            KEMS / "agile_event_priority_runtime.py",
            KEMS / "agile_dashboard_parity.py",
            KEMS / "agile_progressive_publication.py",
            KEMS / "agile_full_battery_routing.py",
            KEMS / "agile_deadline_plan_reconciliation.py",
            KEMS / "agile_publication_reporting.py",
            KEMS / "agile_dispatch_reconciliation.py",
        )
    )
    assert "safe_to_write_hardware = True" not in sources
    assert "commands_permitted = True" not in sources
    assert ".services.async_call(" not in sources


def test_alpha9_2_ohme_write_is_narrow_and_explicitly_opt_in() -> None:
    source = (KEMS / "happy_hour_ohme_control.py").read_text(encoding="utf-8")
    assert "CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED" in source
    assert 'happy_hour.get("source") == "octopus_energy"' in source
    assert '"select",' in source and '"select_option",' in source
    assert "from .foxess" not in source
    assert "FoxESSCommand" not in source
