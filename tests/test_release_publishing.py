"""Regression guards for canonical automatic KEMS release publishing."""

from __future__ import annotations

from pathlib import Path

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
