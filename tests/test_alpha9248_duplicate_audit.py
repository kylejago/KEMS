"""Alpha9.248 audit tools must only identify exact duplicates, never delete them."""

from pathlib import Path

import pytest

from scripts.audit_duplicate_runtime_modules import duplicate_python_modules


def test_exact_duplicate_inventory_does_not_modify_modules(tmp_path: Path) -> None:
    directory = tmp_path / "custom_components" / "kems"
    directory.mkdir(parents=True)
    original = "def calculate():\n    return 7\n"
    (directory / "alpha_legacy.py").write_text(original)
    (directory / "semantic_runtime.py").write_text(original)
    (directory / "separate.py").write_text("def calculate():\n    return 8\n")

    groups = duplicate_python_modules(tmp_path)

    assert len(groups) == 1
    assert groups[0]["bytes_per_file"] == len(original.encode("utf-8"))
    assert groups[0]["paths"] == [
        "custom_components/kems/alpha_legacy.py",
        "custom_components/kems/semantic_runtime.py",
    ]
    assert all(path.exists() for path in directory.glob("*.py"))
    assert (directory / "alpha_legacy.py").read_text() == original


def test_duplicate_inventory_rejects_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="KEMS integration directory not found"):
        duplicate_python_modules(tmp_path)
