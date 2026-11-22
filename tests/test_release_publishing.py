"""Regression guards for canonical automatic KEMS release publishing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-kems-release.yml"


def test_release_workflow_publishes_from_main_without_leading_v() -> None:
    """Merged version bumps should publish the exact manifest version automatically."""
    content = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in content
    assert "- main" in content
    assert 'manifest["version"]' in content
    assert '"$VERSION" == v*' in content
    assert 'gh release create "$VERSION"' in content
    assert '--target "$GITHUB_SHA"' in content
    assert "--prerelease" in content


def test_release_workflow_bundles_from_the_exact_tag() -> None:
    """Bundle assets must be rendered from the immutable release tag."""
    content = WORKFLOW.read_text(encoding="utf-8")

    assert 'git fetch --force origin "refs/tags/$VERSION:refs/tags/$VERSION"' in content
    assert 'git checkout --detach "$VERSION"' in content
    assert "python scripts/render_update_bundle.py \\" in content
    assert '--release-version "$VERSION"' in content
    assert "sha256sum kems-bundle.json > kems-bundle.json.sha256" in content
    assert 'gh release upload "$VERSION"' in content
    assert "--clobber" in content


def test_release_workflow_has_write_permission_and_serialises_publication() -> None:
    """Publishing requires contents write and must not race two release jobs."""
    content = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: write" in content
    assert "group: publish-kems-release" in content
    assert "cancel-in-progress: false" in content


def test_release_requires_exact_main_commit_ci_before_creating_tag() -> None:
    """A successful earlier PR or unrelated SHA must not authorise publishing."""
    content = WORKFLOW.read_text(encoding="utf-8")

    assert "actions: read" in content
    assert "for workflow in validate.yml hacs.yml hassfest.yml" in content
    assert '--commit "$GITHUB_SHA" --event push' in content
    assert 'row.get("headSha") == os.environ["EXPECTED_SHA"]' in content
    assert 'current.get("conclusion") == "success"' in content
    assert "current_main=" in content
    assert 'if [[ "$current_main" != "$GITHUB_SHA" ]]' in content
    assert content.index("Gate publication on exact-commit") < content.index(
        "Create canonical release when missing"
    )


def test_release_rejects_reusing_a_tag_at_another_commit() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")

    assert 'existing_commit="$(git rev-parse "$VERSION^{commit}")"' in content
    assert 'if [[ "$existing_commit" != "$GITHUB_SHA" ]]' in content
    assert "bump the manifest first" in content


def test_python_314_has_non_hardware_syntax_ci() -> None:
    """Forward-compatible syntax check must not substitute for HA runtime tests."""
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "python-314-syntax:" in workflow
    assert 'python-version: "3.14"' in workflow
    assert "python -m compileall -q custom_components tests scripts" in workflow
    assert 'python-version: "3.13"' in workflow
    assert "run: python -m pytest" in workflow


def test_publisher_gh_run_list_uses_real_shell_line_continuations() -> None:
    """Two escaped backslashes terminate gh and break CI release verification."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    gh_command = [
        line for line in lines if "gh run list --repo" in line or "--event push" in line
    ]
    assert len(gh_command) == 2
    assert all(line.endswith(chr(92)) for line in gh_command)
    assert all(not line.endswith(chr(92) * 2) for line in gh_command)


def test_all_release_publisher_bash_run_blocks_parse() -> None:
    """Catch malformed heredocs/shell syntax before any release is published."""
    for filename in (
        "publish-kems-release.yml",
        "publish-panel-release.yml",
        "publish-update-bundle.yml",
    ):
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        )
        for step in workflow["jobs"]["publish"]["steps"]:
            script = step.get("run")
            if not script:
                continue
            result = subprocess.run(
                ["bash", "-n"],
                input=script,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, (
                f"{filename} step {step.get('name')} has invalid Bash syntax: "
                f"{result.stderr}"
            )


def test_real_ha_python314_runtime_requires_full_unit_suite() -> None:
    """Syntax compilation alone cannot prove KEMS on installed HA Python 3.14."""
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "python-314-full-tests:" in workflow
    assert 'python-version: "3.14"' in workflow
    assert "Full KEMS unit tests on Python 3.14" in workflow
    assert "run: python -m pytest" in workflow
    assert workflow.count("run: python -m pytest") >= 2
