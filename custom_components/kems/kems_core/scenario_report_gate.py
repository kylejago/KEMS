"""Bounded cadence/cache for reporting-only expensive comparison replays.

The KEMS control planner, physical snapshots, EV guards and FoxESS writes must
never depend on this optional reporting value or await its computation.
"""

from __future__ import annotations

from datetime import datetime, timedelta

REPORT_REFRESH = timedelta(minutes=5)


class ScenarioReportGate[T]:
    """Allow one optional reporting replay at a time, with a bounded cadence."""

    def __init__(self, refresh: timedelta = REPORT_REFRESH) -> None:
        self._refresh = refresh
        self._started: datetime | None = None
        self._mode: bool | None = None
        self._running = False
        self._result: T | None = None
        self._result_date = None
        self._result_mode: bool | None = None
        self._completed: datetime | None = None
        self._last_error: str | None = None

    def claim(self, now: datetime, *, detailed: bool) -> bool:
        """Reserve the next report run without touching live authority."""
        if self._running:
            return False
        if (
            self._started is not None
            and self._mode == detailed
            and self._started.date() == now.date()
            and timedelta(0) <= now - self._started < self._refresh
        ):
            return False
        self._started = now
        self._mode = detailed
        self._running = True
        return True

    def complete(self, result: T, *, now: datetime, detailed: bool) -> None:
        """Only publish the result for the active request and reporting mode."""
        if self._running and detailed == self._mode:
            self._result = result
            self._result_date = now.date()
            self._result_mode = detailed
            self._completed = now
            self._last_error = None
        self._running = False

    def fail(self, error: Exception | str) -> None:
        """Keep the last valid report and throttle retries after a failure."""
        self._running = False
        self._last_error = str(error)[:250]

    def cached(self, now: datetime, *, detailed: bool) -> T | None:
        """Never reuse an earlier day's or a different mode's comparison."""
        if self._result_date == now.date() and self._result_mode == detailed:
            return self._result
        return None

    @property
    def status(self) -> dict[str, object]:
        return {
            "mode": (
                "detailed"
                if self._mode
                else "baseline_only" if self._mode is not None else "not_started"
            ),
            "running": self._running,
            "last_started": self._started.isoformat() if self._started else None,
            "last_completed": self._completed.isoformat() if self._completed else None,
            "last_error": self._last_error,
            "cached_result_available": self._result is not None,
            "refresh_seconds": self._refresh.total_seconds(),
            "live_hardware_authority": "unchanged",
        }
