from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_VERSION = "0.9.0-alpha9.44"
NEW_VERSION = "0.9.0-alpha9.45"

manifest_path = ROOT / "custom_components" / "kems" / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("version") != OLD_VERSION:
    raise RuntimeError(f"Unexpected manifest version: {manifest.get('version')}")
manifest["version"] = NEW_VERSION
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

reason_prefix = (
    "Alpha9.45 corrects Weekend Happy Hour reward-count semantics and event-day usage "
    "observability. When KEMS reads Octopus Energy 19.1 through the coordinator fallback, "
    "raw weekend_happy_hours progress is normalised exactly like the upstream public entity "
    "(two successful Power Down units per one banked Happy Hour), so raw 6 reports 3 rewards "
    "rather than 6. KEMS separately exposes the banked reward balance, available candidate "
    "windows, the reward hours redeemable on the event day and the Octopus two-one-hour-reward "
    "event-day limit; a larger banked balance remains banked for future event days. One/two-hour "
    "reward accounting is canonicalised to the existing 16 kWh-per-reward-hour cap so one event "
    "day can never be modelled above two reward hours. Candidate windows remain choices rather "
    "than consumed rewards. Alpha9.45 does not broaden external Octopus booking authority, Happy "
    "Hour economic scoring, tariff policy, SOC arithmetic, commissioning, control eligibility, "
    "Ohme authority or FoxESS hardware-write authority; all existing fail-closed control gates "
    "and real-hardware write blocks remain unchanged. "
)
bundle_path = ROOT / "release" / "kems-bundle.template.json"
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
old_reason = str(bundle["maintenance"]["reason"])
if not old_reason.startswith("Alpha9.44"):
    raise RuntimeError("Release reason is not based on Alpha9.44")
bundle["maintenance"]["reason"] = reason_prefix + old_reason
bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

for path in sorted((ROOT / "tests").glob("test_*.py")):
    text = path.read_text(encoding="utf-8")
    updated = text.replace(OLD_VERSION, NEW_VERSION)
    updated = updated.replace('reason.startswith("Alpha9.44")', 'reason.startswith("Alpha9.45")')
    if updated != text:
        path.write_text(updated, encoding="utf-8")

alpha945 = ROOT / "tests" / "test_alpha945_happy_hour_normalisation.py"
text = alpha945.read_text(encoding="utf-8")
marker = "def test_alpha945_release_identity_and_scope() -> None:"
if marker not in text:
    text += '''\n\ndef test_alpha945_release_identity_and_scope() -> None:\n    import json\n    from pathlib import Path\n\n    root = Path(__file__).parents[1]\n    manifest = json.loads(\n        (root / "custom_components" / "kems" / "manifest.json").read_text(encoding="utf-8")\n    )\n    bundle = json.loads(\n        (root / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")\n    )\n    reason = str(bundle["maintenance"]["reason"])\n    assert manifest["version"] == "0.9.0-alpha9.45"\n    assert reason.startswith("Alpha9.45")\n    assert "raw 6 reports 3 rewards rather than 6" in reason\n    assert "two-one-hour-reward event-day limit" in reason\n    assert "16 kWh-per-reward-hour cap" in reason\n    assert "does not broaden external Octopus booking authority" in reason\n    assert "FoxESS hardware-write authority" in reason\n'''
    alpha945.write_text(text, encoding="utf-8")
