"""Render and validate the shared KEMS coordinated-update bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = ROOT / "release" / "kems-bundle.template.json"


def clean_release_version(value: str) -> str:
    """Normalise a conventional v-prefixed GitHub release tag."""
    value = value.strip()
    if value.startswith("v") and len(value) > 1 and value[1].isdigit():
        return value[1:]
    return value


def validate_bundle(bundle: Any) -> dict[str, Any]:
    """Validate the portable release-bundle contract."""
    if not isinstance(bundle, dict):
        raise ValueError("Bundle must be a JSON object")
    if bundle.get("schema") != 1:
        raise ValueError("Bundle schema must be 1")
    version = str(bundle.get("bundle") or "").strip()
    if not version:
        raise ValueError("Bundle version is required")
    components = bundle.get("components")
    if not isinstance(components, dict):
        raise ValueError("Bundle components must be an object")
    for required in (
        "kems_core",
        "dashboard",
        "panel",
        "property_web",
        "pi_agent",
        "pi_system",
        "public_web",
    ):
        if required not in components or not isinstance(components[required], dict):
            raise ValueError(f"Bundle component {required} is required")
    core_version = str(components["kems_core"].get("version") or "").strip()
    dashboard_version = str(components["dashboard"].get("version") or "").strip()
    if core_version != version:
        raise ValueError("kems_core version must match bundle version")
    if dashboard_version != version:
        raise ValueError("dashboard version must match bundle version")
    property_web = components["property_web"].get("version")
    pi_agent = components["pi_agent"].get("version")
    if property_web and pi_agent and str(property_web) != str(pi_agent):
        raise ValueError(
            "property_web and pi_agent must share one appliance release version"
        )
    maintenance = bundle.get("maintenance")
    if not isinstance(maintenance, dict):
        raise ValueError("Bundle maintenance must be an object")
    affected = maintenance.get("affected_components", [])
    if not isinstance(affected, list):
        raise ValueError("maintenance.affected_components must be a list")
    unknown = [key for key in affected if key not in components]
    if unknown:
        raise ValueError(
            f"Maintenance references unknown components: {', '.join(unknown)}"
        )
    return bundle


def render_bundle(template: Path, release_version: str) -> dict[str, Any]:
    """Render one template for a specific release version."""
    version = clean_release_version(release_version)
    if not version:
        raise ValueError("Release version is required")
    text = template.read_text(encoding="utf-8").replace("__RELEASE_VERSION__", version)
    if "__RELEASE_VERSION__" in text:
        raise ValueError("Unresolved release-version placeholder remains")
    return validate_bundle(json.loads(text))


def main() -> None:
    """CLI entry point used by CI/release automation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = render_bundle(args.template, args.release_version)
    args.output.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
