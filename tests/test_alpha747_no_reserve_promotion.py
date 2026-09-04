"""Regression coverage for Alpha7.47 no-reserve plan promotion."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha746_no_unknown_reserve.py"
DOC = ROOT / "docs" / "alpha747-agile-no-reserve-promotion.md"


def test_alpha747_contract_is_coordinated_in_alpha8() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    web_versions = {
        str(bundle["components"][component]["version"])
        for component in ("property_web", "pi_agent", "public_web")
    }
    assert len(web_versions) == 1 or web_versions == {
        "0.9.0-alpha9-web.0",
        "0.9.0-alpha9-public.0",
    }
    web_version = str(bundle["components"]["property_web"]["version"])
    assert web_version.startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.", "0.9.0-alpha9-public.")
    )
    assert (
        web_version.startswith("0.9.0-alpha9-web.")
        or int(web_version.rsplit(".", 1)[1]) >= 2
    )
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"


def test_alpha747_patch_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha747_uses_verified_octopus_gap_not_missing_publication_pending_key() -> (
    None
):
    source = PATCH.read_text(encoding="utf-8")

    assert 'recovery.get("verified")' in source
    assert 'recovery.get("recovery_outcome") == "octopus_missing_price"' in source
    assert 'recovery.get("publication_pending")' not in source
    assert 'horizon.get("current_slot_known")' in source
    assert 'current_price.get("known")' in source


def test_alpha747_promotes_known_price_plan_and_resets_unknown_reserve_to_zero() -> (
    None
):
    source = PATCH.read_text(encoding="utf-8")

    assert 'plan["provisional_reserved_unknown_capacity_kwh"] = required' in source
    assert '"provisional_reserved_unknown_capacity_kwh": 0.0' in source
    assert '"publication_gap_no_reserve_active": True' in source
    assert '"dispatch_mode": "progressive_known_prices_no_reserve"' in source
    assert '"unknown_price_reservation_policy": "none"' in source
    assert '"replan_when_price_publishes": True' in source


def test_alpha747_preserves_conservative_fallback_and_hardware_block() -> None:
    source = PATCH.read_text(encoding="utf-8")
    docs = DOC.read_text(encoding="utf-8")

    assert "alpha746_original_apply(" in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "retrieval failures remain conservative" in docs.lower()
    assert "Real FoxESS hardware writes remain blocked" in docs
