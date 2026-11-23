"""Alpha9.250: verified physical forecast display and safe GitHub fallback."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from kems_core.github_release_atom import (
    fetch_public_alpha_release_pair,
    public_release_asset_url,
    select_public_alpha_tag,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components/kems"
BRANCH_RELIABLE = KEMS / "update_orchestrator_reliable.py"
BRANCH_CONVERGENT = KEMS / "update_orchestrator_convergent.py"
ROUTING = KEMS / "agile_routing_card_labels.py"
BUDGET = KEMS / "agile_physical_export_budget.py"


def _budget_module():
    spec = importlib.util.spec_from_file_location("alpha9250_physical_budget", BUDGET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_evening_plan():
    """23 November 18:23 same-scan figures, with no future stored solar."""
    return {
        "available": True,
        "planning_soc_percent": 29.838,
        "household_hard_floor_soc_percent": 10.0,
        "predicted_house_battery_discharge_kwh": 5.024,
        "physical_planning_evidence": {
            "available": True,
            "physical_energy_lower_bound_kwh": 14.704,
        },
        "physical_house_budget_evidence": {
            "available": True,
            "exportable_stored_kwh": 0.672,
            "exportable_ac_kwh": 0.638,
        },
        "forecast_path_scheduler": {
            "available": True,
            "ending_soc_percent": 10.0,
            "planned_battery_export_kwh": 4.263,
            "forecast_solar_stored_kwh": 0.0,
        },
    }


def test_conditional_physical_projection_does_not_claim_ten_percent_arrival():
    projection = _budget_module().reconcile_guarded_arrival_soc(
        _live_evening_plan(), final_export_ac_kwh=0.638
    )
    assert projection["status"] == "guarded_physical_budget_projection"
    assert projection["theoretical_model_ending_soc_percent"] == 10.0
    assert projection[
        "theoretical_export_above_guarded_budget_ac_kwh"
    ] == pytest.approx(3.625)
    assert 17.0 < projection["guarded_conditional_ending_soc_percent"] < 19.0
    assert projection["arrival_guaranteed"] is False
    assert projection["reporting_only"] is True
    assert projection["hardware_writes"] == "forbidden"


def test_physical_projection_requires_verified_same_scan_budget_and_zero_solar():
    module = _budget_module()
    for mutation in ("physical", "budget", "solar", "efficiency"):
        plan = _live_evening_plan()
        if mutation == "physical":
            plan["physical_planning_evidence"]["available"] = False
        elif mutation == "budget":
            plan["physical_house_budget_evidence"]["available"] = False
        elif mutation == "solar":
            plan["forecast_path_scheduler"]["forecast_solar_stored_kwh"] = 1.0
        else:
            plan["physical_house_budget_evidence"]["exportable_stored_kwh"] = 0.0
        result = module.reconcile_guarded_arrival_soc(plan, final_export_ac_kwh=0.638)
        assert result["status"] == "unavailable"
        assert result["guarded_conditional_ending_soc_percent"] is None


def test_final_export_cap_merely_attaches_report_and_preserves_guard_authority():
    source = BUDGET.read_text(encoding="utf-8")
    assert "reconcile_guarded_arrival_soc(" in source
    assert '"forecast_path_budget_reconciliation"' in source
    assert '"forecast_path_reconciled_ending_soc_percent"' in source
    assert 'plan["planned_total_battery_discharge_kwh"]' in source
    assert '"current_battery_export_target_kw": round(export_kw, 3)' in source
    assert "independent 15% deliberate-export/10% home floor" in source
    assert ".services.async_call" not in source


def test_current_routing_dashboard_distinguishes_proposal_guard_and_ct():
    source = ROUTING.read_text(encoding="utf-8")
    for expected in (
        "Proposed grid export (before physical guard)",
        "Proposed battery → export (before physical guard)",
        "Final KEMS battery export target (after physical guard)",
        "Grid export measured (FoxESS CT)",
        "Guarded conditional SOC at cheap start",
        "one current KEMS coordinator routing snapshot",
    ):
        assert expected in source
    assert "sensor.kems_desired_battery_export_power" in source
    assert "sensor.kems_grid_export" in source
    assert "sensor.kems_agile_rolling_export_plan" in source
    assert "install_alpha9250_routing_card_labels()" in (
        KEMS / "agile_smart_export_runtime.py"
    ).read_text(encoding="utf-8")
    assert "providers.foxess" not in source


def _atom(*tags: str) -> bytes:
    body = "".join(
        '<entry><link rel="alternate" href="https://github.com/kylejago/KEMS/'
        f'releases/tag/{tag}"/></entry>'
        for tag in tags
    )
    return ('<feed xmlns="http://www.w3.org/2005/Atom">' + body + "</feed>").encode()


def test_atom_feed_selects_highest_canonical_published_alpha_tag():
    assert (
        select_public_alpha_tag(
            _atom(
                "0.9.0-alpha9.248",
                "v0.9.0-alpha9.300",
                "0.9.0-alpha9.249",
                "0.9.0-alpha9.250",
            )
        )
        == "0.9.0-alpha9.250"
    )
    assert (
        select_public_alpha_tag(
            b'<feed xmlns="http://www.w3.org/2005/Atom">'
            b'<entry><link href="https://evil.example/kylejago/KEMS/releases/tag/'
            b'0.9.0-alpha9.999"/></entry></feed>'
        )
        is None
    )
    assert select_public_alpha_tag(_atom("0.9.0-alpha9.249%2Ffake")) is None
    with pytest.raises(ValueError, match="unexpected root"):
        select_public_alpha_tag(b"<html/>")


def test_atom_asset_urls_are_fixed_repository_and_bounded_files():
    assert public_release_asset_url("0.9.0-alpha9.250", "kems-bundle.json").startswith(
        "https://github.com/kylejago/KEMS/releases/download/"
    )
    for tag, name in (
        ("0.9.0-alpha9.250/../../other", "kems-bundle.json"),
        ("v0.9.0-alpha9.250", "kems-bundle.json"),
        ("0.9.0-alpha9.250", "payload.py"),
    ):
        with pytest.raises(ValueError, match="untrusted"):
            public_release_asset_url(tag, name)


class _PublicResponse:
    def __init__(
        self, body: bytes, url: str, *, status=200, media="application/octet-stream"
    ):
        self.content = SimpleNamespace(read=self._read)
        self.body = body
        self.url = url
        self.status = status
        self.headers = {"Content-Type": media}

    async def _read(self, bound: int):
        return self.body[:bound]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _PublicSession:
    def __init__(self, tag: str, manifest: bytes, checksum: bytes, *, html=False):
        self.tag = tag
        self.manifest = manifest
        self.checksum = checksum
        self.html = html
        self.calls: list[str] = []

    def get(self, url: str, *, headers, timeout, allow_redirects=True):
        self.calls.append(url)
        if url.endswith("/releases.atom"):
            return _PublicResponse(_atom(self.tag), url, media="application/atom+xml")
        if url.endswith("/kems-bundle.json.sha256"):
            return _PublicResponse(
                self.checksum,
                "https://release-assets.githubusercontent.com/checksum",
            )
        if url.endswith("/kems-bundle.json"):
            return _PublicResponse(
                self.manifest,
                "https://release-assets.githubusercontent.com/manifest",
                media="text/html" if self.html else "application/octet-stream",
            )
        raise AssertionError(f"unplanned public request: {url}")


def test_public_fallback_fetches_only_published_release_pair():
    tag = "0.9.0-alpha9.250"
    manifest = b'{"bundle":"0.9.0-alpha9.250"}'
    digest = hashlib.sha256(manifest).hexdigest().encode()
    session = _PublicSession(tag, manifest, digest)
    got = asyncio.run(fetch_public_alpha_release_pair(session, user_agent="KEMS-test"))
    assert got == (tag, manifest, digest)
    assert len(session.calls) == 3
    assert all(
        url.startswith("https://github.com/kylejago/KEMS/") for url in session.calls
    )


def test_public_fallback_rejects_login_or_html_instead_of_bundle():
    session = _PublicSession(
        "0.9.0-alpha9.250", b"<html>login</html>", b"unused", html=True
    )
    with pytest.raises(ValueError, match="HTML"):
        asyncio.run(fetch_public_alpha_release_pair(session, user_agent="KEMS-test"))


def test_active_manual_install_requires_running_files_and_dashboard_match():
    source = BRANCH_CONVERGENT.read_text(encoding="utf-8")
    assert "self.pending and self.latest_bundle is None" in source
    assert "base._version_matches(target, running)" in source
    assert "base._version_matches(target, disk)" in source
    assert "self._dashboard_current() is True" in source
    assert '"already_active_local_core_and_dashboard"' in source
    assert '"external_components_verified": False' in source
    assert "Preserve any metadata lookup error" in source


def test_fallback_remains_alpha_only_and_sha256_pinned():
    source = BRANCH_RELIABLE.read_text(encoding="utf-8")
    assert 'response.status in (403, 429) and self.policy.channel == "alpha"' in source
    assert "fetch_public_alpha_release_pair" in source
    assert "max_field_size=65536" in source
    assert "hashlib.sha256(manifest_bytes).hexdigest()" in source
    assert "base._version_matches(tag, target)" in source
    assert "download_release_asset_pair(" in source
