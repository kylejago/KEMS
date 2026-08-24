"""Regression contracts for the Alpha8.12 dashboard and release cleanup."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD_RUNTIME = ROOT / "custom_components" / "kems" / "dashboard.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"

UNSAFE_FAILURE_TEMPLATE = (
    "{% set failure = update.attributes.last_error or maintenance.attributes.error %}"
)
SAFE_FAILURE_TEMPLATE = (
    "{% set failure = update.attributes.get('last_error') or "
    "maintenance.attributes.get('error') %}"
)


def _load_readability_pass() -> Callable[[str], str]:
    source = DASHBOARD_RUNTIME.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_dashboard_readability_pass"
    )
    namespace: dict[str, object] = {}
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            str(DASHBOARD_RUNTIME),
            "exec",
        ),
        namespace,
    )
    return namespace["_dashboard_readability_pass"]  # type: ignore[return-value]


def test_alpha8_12_managed_dashboard_hardens_missing_optional_error_attributes() -> (
    None
):
    readability_pass = _load_readability_pass()
    rendered = readability_pass(UNSAFE_FAILURE_TEMPLATE)

    assert SAFE_FAILURE_TEMPLATE in rendered
    assert UNSAFE_FAILURE_TEMPLATE not in rendered


def test_alpha8_12_release_scope_is_ha_and_dashboard_only() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert manifest["version"] == "0.8.0-alpha8.12"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.3"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.3"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.3"
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
    ]
    assert "managed Home Assistant dashboard" in bundle["maintenance"]["reason"]
