# KEMS v0.6.0-beta1 main release

1. Start from the tested `develop` branch containing alpha5 and the Power Down dashboard hotfix.
2. Copy this package over the repository root, preserving `.git`.
3. Run Black, Ruff, pytest, and pre-commit.
4. Commit as `release: prepare v0.6.0-beta1`.
5. Merge `develop` into `main`.
6. Create and push tag `v0.6.0-beta1`.
7. Create a GitHub release from that tag using the changelog entry.
8. Keep `main` as the read-only rollback baseline while control work continues on `develop`.
