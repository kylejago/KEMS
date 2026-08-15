"""Apply final Ruff/safety fixes to the update orchestrator once."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "custom_components" / "kems" / "update_orchestrator.py"
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "import logging\nfrom dataclasses import asdict, dataclass\n",
        "import logging\nfrom contextlib import suppress\nfrom dataclasses import asdict, dataclass\n",
    ),
    (
        'def from_dict(cls, raw: dict[str, Any] | None) -> "UpdatePolicy":',
        "def from_dict(cls, raw: dict[str, Any] | None) -> UpdatePolicy:",
    ),
    (
        '''    core = components.get("kems_core")
    if core is not None:
        if not isinstance(core, dict) or not str(core.get("version", "")).strip():
            raise ValueError("KEMS bundle kems_core target is invalid")
''',
        '''    core = components.get("kems_core")
    if core is not None and (
        not isinstance(core, dict) or not str(core.get("version", "")).strip()
    ):
        raise ValueError("KEMS bundle kems_core target is invalid")
''',
    ),
    (
        '''                raise HomeAssistantError(
                    f"Release {release.get('tag_name')} has a KEMS bundle without its SHA-256 asset"
                )
''',
        '''                raise HomeAssistantError(
                    f"Release {release.get('tag_name')} has a KEMS bundle "
                    "without its SHA-256 asset"
                )
''',
    ),
    (
        '''                else:
                    LOGGER.warning(
                        "KEMS pre-update backup requested but backup.create_automatic is unavailable"
                    )
''',
        '''                else:
                    await self._fail_pending(
                        "Pre-update backup requested, but "
                        "backup.create_automatic is unavailable"
                    )
                    return
''',
    ),
    (
        '''        if scheduled:
            try:
                when = dt_util.as_local(
                    datetime.fromisoformat(str(scheduled))
                ).strftime("%a %d %b %H:%M")
            except ValueError:
                pass
''',
        '''        if scheduled:
            with suppress(ValueError):
                when = dt_util.as_local(
                    datetime.fromisoformat(str(scheduled))
                ).strftime("%a %d %b %H:%M")
''',
    ),
    (
        '''            message = f"KEMS {target} is active and all required local components passed verification. Everything is up to date."
''',
        '''            message = (
                f"KEMS {target} is active and all required local components "
                "passed verification. Everything is up to date."
            )
''',
    ),
    (
        '''            message = f"The coordinated update did not complete: {pending.get('error') or self.last_error or reason}"
''',
        '''            error = pending.get("error") or self.last_error or reason
            message = f"The coordinated update did not complete: {error}"
''',
    ),
    (
        '''            message = f"KEMS {target} is installed. Home Assistant must restart to activate it. Reason: {reason}."
''',
        '''            message = (
                f"KEMS {target} is installed. Home Assistant must restart to "
                f"activate it. Reason: {reason}."
            )
''',
    ),
    (
        '''            message = f"Home Assistant is restarting to activate KEMS {target}. Expected interruption: about {downtime} minutes."
''',
        '''            message = (
                f"Home Assistant is restarting to activate KEMS {target}. "
                f"Expected interruption: about {downtime} minutes."
            )
''',
    ),
    (
        '''            message = f"KEMS {target} is scheduled for {when}. Reason: {reason}. Expected interruption: about {downtime} minutes. No action is required."
''',
        '''            message = (
                f"KEMS {target} is scheduled for {when}. Reason: {reason}. "
                f"Expected interruption: about {downtime} minutes. "
                "No action is required."
            )
''',
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"Expected replacement anchor not found: {old[:120]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

for transient in (
    ROOT / "scripts" / "fix_update_orchestrator_ruff_once.py",
    ROOT / ".github" / "workflows" / "fix-update-orchestrator-ruff-once.yml",
):
    transient.unlink(missing_ok=True)
