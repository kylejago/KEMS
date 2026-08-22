"""Keep release literals out of runtime implementation filenames."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def test_alpha8_release_numbers_do_not_name_runtime_modules() -> None:
    runtime_names = [path.name.lower() for path in INTEGRATION.glob("*.py")]

    assert not any("alpha8.1" in name or "alpha81" in name for name in runtime_names)
