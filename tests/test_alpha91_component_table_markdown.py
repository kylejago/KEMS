"""Regression guards for Alpha9.1 dynamic Markdown table rendering."""

from __future__ import annotations

import textwrap
from pathlib import Path

from jinja2 import Template

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"


def _card_template(title: str, next_title: str | None = None) -> str:
    text = DASHBOARD.read_text(encoding="utf-8")
    title_marker = f"        title: {title}\n"
    start = text.index(title_marker)
    content_start = text.index("        content: |\n", start) + len(
        "        content: |\n"
    )
    if next_title is None:
        end = len(text)
    else:
        end = text.index(f"        title: {next_title}\n", content_start)
        prior_card = text.rfind("      - type: markdown\n", content_start, end)
        if prior_card >= content_start:
            end = prior_card
    return textwrap.dedent(text[content_start:end]).rstrip()


def test_component_verification_rows_render_contiguously() -> None:
    card = _card_template("Component verification", "Recent updates — latest 5")
    components = [
        {
            "key": "kems_core",
            "installed": "0.9.0-alpha9.1",
            "target": "0.9.0-alpha9.1",
            "status": "current",
        },
        {
            "key": "property_web",
            "installed": None,
            "target": "0.9.0-alpha9-web.0",
            "status": "delegated",
        },
    ]

    def state_attr(_entity: str, attribute: str):
        return components if attribute == "components" else None

    rendered = Template(card).render(state_attr=state_attr)
    lines = [line for line in rendered.splitlines() if line]
    assert lines[:4] == [
        "| Component | Installed | Target | Status |",
        "|---|---|---|---|",
        "| kems_core | 0.9.0-alpha9.1 | 0.9.0-alpha9.1 | current |",
        "| property_web | — | 0.9.0-alpha9-web.0 | delegated |",
    ]
    assert "\n\n| kems_core" not in rendered
    assert "\n\n| property_web" not in rendered


def test_recent_update_rows_render_contiguously() -> None:
    card = _card_template("Recent updates — latest 5")
    history = [
        {
            "completed_at": "2026-09-04T22:07:45+01:00",
            "bundle": "0.9.0-alpha9.0",
            "result": "success",
        },
        {
            "completed_at": "2026-09-04T23:00:00+01:00",
            "bundle": "0.9.0-alpha9.1",
            "result": "success",
        },
    ]

    def state_attr(_entity: str, attribute: str):
        return history if attribute == "history" else None

    rendered = Template(card).render(state_attr=state_attr)
    lines = [line for line in rendered.splitlines() if line]
    assert lines[:4] == [
        "| Completed | Bundle | Result |",
        "|---|---|---|",
        "| 2026-09-04T23:00:00 | 0.9.0-alpha9.1 | success |",
        "| 2026-09-04T22:07:45 | 0.9.0-alpha9.0 | success |",
    ]
    assert "\n\n| 2026-09-04T23:00:00" not in rendered
