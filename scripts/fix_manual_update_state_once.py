"""Keep opt-out update discovery distinct from scheduled maintenance once."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "custom_components" / "kems" / "update_orchestrator.py"
text = path.read_text(encoding="utf-8")

old = '''        scheduled_for = None
        if disruptive:
            scheduled_for = self._scheduled_time().isoformat()
        self.pending = {
            "bundle": bundle.get("bundle"),
            "target": target,
            "discovered_at": dt_util.now().isoformat(),
            "scheduled_for": scheduled_for,
            "stage": "scheduled" if disruptive else "ready",
            "reason": reason,
            "maintenance": maintenance,
            "source": self.bundle_source,
        }
        self.maintenance = self._maintenance_payload("scheduled", self.pending)
        if self.policy.notify_before_disruption:
            await self._async_notify("scheduled", self.pending)
        if self.policy.automatic_updates:
            await self._maybe_run_pending()
'''
new = '''        automatic = self.policy.automatic_updates
        scheduled_for = None
        if automatic and disruptive:
            scheduled_for = self._scheduled_time().isoformat()
        self.pending = {
            "bundle": bundle.get("bundle"),
            "target": target,
            "discovered_at": dt_util.now().isoformat(),
            "scheduled_for": scheduled_for,
            "stage": (
                "available"
                if not automatic
                else "scheduled" if disruptive else "ready"
            ),
            "reason": reason,
            "maintenance": maintenance,
            "source": self.bundle_source,
        }
        notice_status = "scheduled" if automatic and disruptive else "update_available"
        self.maintenance = self._maintenance_payload(notice_status, self.pending)
        if self.policy.notify_before_disruption:
            await self._async_notify(
                "scheduled" if automatic and disruptive else "available",
                self.pending,
            )
        if automatic:
            await self._maybe_run_pending()
'''
if old not in text:
    raise SystemExit("consider bundle anchor not found")
text = text.replace(old, new, 1)

old = '''        disruptive = bool(self.pending.get("maintenance", {}).get("required", True))
        if disruptive and not self._in_maintenance_window():
            return
'''
new = '''        disruptive = bool(self.pending.get("maintenance", {}).get("required", True))
        if disruptive and not self._in_maintenance_window():
            if self.pending.get("stage") != "scheduled":
                self.pending["stage"] = "scheduled"
                self.pending["scheduled_for"] = self._scheduled_time().isoformat()
                self.maintenance = self._maintenance_payload("scheduled", self.pending)
                if self.policy.notify_before_disruption:
                    await self._async_notify("scheduled", self.pending)
                await self._async_save()
            return
'''
if old not in text:
    raise SystemExit("maybe run pending anchor not found")
text = text.replace(old, new, 1)

old = '''        if phase == "completed":
            title = "KEMS maintenance complete"
'''
new = '''        if phase == "available":
            title = "KEMS update available"
            message = (
                f"KEMS {target} is available. Automatic updates are disabled, "
                "so no maintenance has been scheduled."
            )
        elif phase == "completed":
            title = "KEMS maintenance complete"
'''
if old not in text:
    raise SystemExit("notification phase anchor not found")
text = text.replace(old, new, 1)

old = '''        if self.pending:
            stage = str(self.pending.get("stage") or "scheduled")
            if stage in {"installing", "restart_requested", "verifying"}:
                return "Updating"
            return "Update scheduled"
'''
new = '''        if self.pending:
            stage = str(self.pending.get("stage") or "scheduled")
            if stage in {"installing", "restart_requested", "verifying"}:
                return "Updating"
            if stage in {"available", "ready"}:
                return "Update available"
            return "Update scheduled"
'''
if old not in text:
    raise SystemExit("status label anchor not found")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

for transient in (
    ROOT / "scripts" / "fix_manual_update_state_once.py",
    ROOT / ".github" / "workflows" / "fix-manual-update-state-once.yml",
):
    transient.unlink(missing_ok=True)
