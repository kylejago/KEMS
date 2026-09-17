"""Alpha9.51 Power Down post-event history and accounting presentation.

This compatibility layer is reporting-only. It retains multiple completed Power
Down results, makes completed same-day reward evidence authoritative for the
customer-facing KEMS event credit, and exposes that history to the managed
dashboard. It does not alter joining, dispatch, optimiser, commissioning or
hardware-write authority.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from homeassistant.util import dt as dt_util

from .kems_core import PowerDownResult, SimulationState

_INSTALLED = False
_ACTIVE_RECORDER: Any | None = None
_MAX_HISTORY = 64


def _normalise_history(values: Any) -> list[PowerDownResult]:
    """Return deduplicated retained completed results in chronological order."""
    results: dict[str, PowerDownResult] = {}
    if isinstance(values, list):
        for item in values:
            if not isinstance(item, dict):
                continue
            result = PowerDownResult.from_dict(item)
            if not result.available or not result.session_id:
                continue
            results[str(result.session_id)] = result
    ordered = sorted(
        results.values(),
        key=lambda item: item.session_end or item.session_start or dt_util.utcnow(),
    )
    return ordered[-_MAX_HISTORY:]


def _local_date(value) -> date | None:
    """Return the Home Assistant local date for one aware event timestamp."""
    if value is None:
        return None
    try:
        return dt_util.as_local(value).date()
    except (TypeError, ValueError):
        return None


def _results_for_date(recorder: Any, target: date) -> list[PowerDownResult]:
    """Return all completed Power Down results whose event ended on target."""
    history = getattr(recorder, "_completed_history", [])
    return [
        item
        for item in history
        if isinstance(item, PowerDownResult)
        and item.available
        and _local_date(item.session_end or item.session_start) == target
    ]


def _result_dict(result: PowerDownResult) -> dict[str, Any]:
    """Return one dashboard-safe completed result payload."""
    payload = result.to_dict()
    payload["authority"] = "KEMS retained completed-event result"
    payload["supplier_settled"] = False
    return payload


def _today_completed_results() -> list[PowerDownResult]:
    recorder = _ACTIVE_RECORDER
    if recorder is None:
        return []
    return _results_for_date(recorder, dt_util.now().date())


def _authoritative_today_bonus(simulation: SimulationState) -> float | None:
    """Return same-day completed credit plus any distinct live event estimate."""
    completed = _today_completed_results()
    if not completed:
        return None

    bonus = sum(max(float(item.bonus_pence or 0.0), 0.0) for item in completed)
    now = dt_util.now()
    current_end = simulation.saving_session_end
    current_open = bool(
        simulation.saving_session_joined
        and current_end is not None
        and current_end > now
        and _local_date(current_end) == now.date()
    )
    if current_open and simulation.estimated_saving_session_bonus_pence is not None:
        bonus += max(float(simulation.estimated_saving_session_bonus_pence), 0.0)
    return round(bonus, 2)


def _reconcile_completed_credit(simulation: SimulationState) -> SimulationState:
    """Replace stale event estimate with retained completed same-day evidence."""
    authoritative = _authoritative_today_bonus(simulation)
    if authoritative is None:
        return simulation

    previous = float(simulation.simulated_saving_session_bonus_pence or 0.0)
    delta = round(authoritative - previous, 2)
    replacements: dict[str, Any] = {
        "simulated_saving_session_bonus_pence": authoritative,
    }
    if simulation.simulated_cost_pence is not None:
        replacements["simulated_cost_pence"] = round(
            simulation.simulated_cost_pence - delta,
            2,
        )
    if simulation.saving_pence is not None:
        replacements["saving_pence"] = round(simulation.saving_pence + delta, 2)
    if simulation.simulated_system_value_pence is not None:
        replacements["simulated_system_value_pence"] = round(
            simulation.simulated_system_value_pence + delta,
            2,
        )
    return replace(simulation, **replacements)


def _install_history_patch() -> None:
    """Persist a bounded deduplicated completed-event history."""
    from . import power_down

    cls = power_down.PowerDownHistoryRecorder
    if getattr(cls, "_alpha951_history_patch", False):
        return

    original_init = cls.__init__
    original_load = cls.async_load
    original_update = cls.async_update

    def patched_init(self, *args, **kwargs):
        global _ACTIVE_RECORDER
        original_init(self, *args, **kwargs)
        self._completed_history = []
        _ACTIVE_RECORDER = self

    async def patched_load(self):
        global _ACTIVE_RECORDER
        await original_load(self)
        stored = await self._store.async_load()
        history = _normalise_history(
            stored.get("completed_history", []) if isinstance(stored, dict) else []
        )
        if not history and self._last.available and self._last.session_id:
            history = [self._last]
        self._completed_history = history
        _ACTIVE_RECORDER = self

    async def patched_update(self, *args, **kwargs):
        result = await original_update(self, *args, **kwargs)
        if result.available and result.session_id:
            by_id = {
                str(item.session_id): item
                for item in getattr(self, "_completed_history", [])
                if item.available and item.session_id
            }
            by_id[str(result.session_id)] = result
            self._completed_history = sorted(
                by_id.values(),
                key=lambda item: item.session_end
                or item.session_start
                or dt_util.utcnow(),
            )[-_MAX_HISTORY:]
            await self.async_save()
        return result

    async def patched_save(self):
        await self._store.async_save(
            {
                "last_result": self._last.to_dict(),
                "pending": self._pending,
                "completed_history": [
                    item.to_dict()
                    for item in getattr(self, "_completed_history", [])[-_MAX_HISTORY:]
                ],
            }
        )

    def results_for_local_date(self, target: date) -> list[PowerDownResult]:
        return _results_for_date(self, target)

    cls.__init__ = patched_init
    cls.async_load = patched_load
    cls.async_update = patched_update
    cls.async_save = patched_save
    cls.results_for_local_date = results_for_local_date
    cls._alpha951_history_patch = True


def _install_presentation_patch() -> None:
    """Use completed event evidence in the customer-facing daily KEMS totals."""
    from . import agile_current_day_presentation as presentation
    from . import coordinator

    if getattr(presentation, "_alpha951_power_down_patch", False):
        return
    original = presentation.reconciled_current_day_simulation

    def patched(simulation, state):
        return _reconcile_completed_credit(original(simulation, state))

    presentation.reconciled_current_day_simulation = patched
    coordinator.reconciled_current_day_simulation = patched
    presentation._alpha951_power_down_patch = True


def _install_binary_sensor_patch() -> None:
    """Expose today's retained completed events as dashboard state attributes."""
    from . import binary_sensor

    cls = binary_sensor.KEMSBinarySensor
    if getattr(cls, "_alpha951_power_down_patch", False):
        return
    original = cls.extra_state_attributes.fget

    def extra_state_attributes(self):
        attrs = original(self) if original is not None else None
        if self.entity_description.key != "last_power_down_available":
            return attrs

        recorder = getattr(self.coordinator, "_power_down", None)
        today = dt_util.now().date()
        completed = (
            recorder.results_for_local_date(today)
            if recorder is not None and hasattr(recorder, "results_for_local_date")
            else []
        )
        result = dict(attrs) if isinstance(attrs, dict) else {}
        result.update(
            {
                "completed_sessions_today": [_result_dict(item) for item in completed],
                "completed_session_count_today": len(completed),
                "completed_bonus_today_pence": round(
                    sum(max(float(item.bonus_pence or 0.0), 0.0) for item in completed),
                    2,
                ),
                "power_down_credit_today_pence": round(
                    float(
                        self.coordinator.data.simulation.simulated_saving_session_bonus_pence
                        or 0.0
                    ),
                    2,
                ),
                "credit_authority": (
                    "KEMS retained completed-event result"
                    if completed
                    else "current KEMS event estimate"
                ),
                "supplier_settled": False,
            }
        )
        return result

    cls.extra_state_attributes = property(extra_state_attributes)
    cls._alpha951_power_down_patch = True


def _install_dashboard_patch() -> None:
    """Restore an explicit Power Down event-credit row in KEMS daily costs."""
    from . import dashboard_pipeline

    if getattr(dashboard_pipeline, "_alpha951_power_down_patch", False):
        return
    original = dashboard_pipeline._finalise_dashboard_bytes
    marker = (
        "              | Export income | −£{{ '%.2f' | format(export / 100) }} |\n"
        "              | **Electricity total**"
    )
    replacement = (
        "              | Export income | −£{{ '%.2f' | format(export / 100) }} |\n"
        "              | Power Down event credit | −£{{ '%.2f' | format((state_attr('binary_sensor.kems_last_power_down_result_available', 'power_down_credit_today_pence') | float(0)) / 100) }} |\n"
        "              | **Electricity total**"
    )

    def patched(payload: bytes) -> bytes:
        rendered = original(payload)
        text = rendered.decode("utf-8")
        # Only the KEMS parity block contains this exact simulated-cost marker;
        # keep the Live Data ledger untouched.
        kems_start = text.find("\n  - title: KEMS\n")
        compare_start = text.find("\n  - title: Compare\n", kems_start + 1)
        if kems_start >= 0 and compare_start > kems_start:
            section = text[kems_start:compare_start]
            section = section.replace(marker, replacement, 1)
            text = text[:kems_start] + section + text[compare_start:]
        return text.encode("utf-8")

    dashboard_pipeline._finalise_dashboard_bytes = patched
    dashboard_pipeline._alpha951_power_down_patch = True


def _install_diagnostics_patch() -> None:
    """Expose retained history and same-day credit authority in diagnostics."""
    from . import diagnostics

    if getattr(diagnostics, "_alpha951_power_down_patch", False):
        return
    original = diagnostics.async_get_config_entry_diagnostics

    async def patched(hass, entry):
        payload = await original(hass, entry)
        recorder = getattr(entry.runtime_data, "_power_down", None)
        history = getattr(recorder, "_completed_history", []) if recorder else []
        today = dt_util.now().date()
        completed_today = (
            recorder.results_for_local_date(today)
            if recorder is not None and hasattr(recorder, "results_for_local_date")
            else []
        )
        payload["power_down_history"] = {
            "retained_count": len(history),
            "completed_today_count": len(completed_today),
            "completed_today": [_result_dict(item) for item in completed_today],
            "completed_bonus_today_pence": round(
                sum(max(float(item.bonus_pence or 0.0), 0.0) for item in completed_today),
                2,
            ),
            "published_power_down_credit_today_pence": round(
                float(
                    entry.runtime_data.data.simulation.simulated_saving_session_bonus_pence
                    or 0.0
                ),
                2,
            ),
            "supplier_settled": False,
            "authority_note": (
                "Completed same-day KEMS event results are authoritative for the "
                "published KEMS Power Down credit; Octopus supplier settlement may differ."
            ),
        }
        return payload

    diagnostics.async_get_config_entry_diagnostics = patched
    diagnostics._alpha951_power_down_patch = True


def install_alpha951_power_down_post_event() -> None:
    """Install Alpha9.51 reporting-only Power Down post-event corrections."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_history_patch()
    _install_presentation_patch()
    _install_binary_sensor_patch()
    _install_dashboard_patch()
    _install_diagnostics_patch()
    _INSTALLED = True
