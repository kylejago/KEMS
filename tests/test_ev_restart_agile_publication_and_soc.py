"""Regression guards for connected-EV cheap restart and Agile reporting scope.

No Home Assistant installation is required to test the pure guard. The
integration's live authority, tariff calculations and all cached replay
invalidations retain their existing independent tests.
"""

from __future__ import annotations

import ast
from math import ceil, isfinite
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _guard():
    path = ROOT / "foxess_control_backend.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_number", "_cheap_ev_restart_protective_floor"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(nodes) == 2
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = {"ceil": ceil, "isfinite": isfinite}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["_cheap_ev_restart_protective_floor"]


def test_ev_restart_prearms_only_confirmed_cheap_connected_self_use() -> None:
    guard = _guard()
    base = dict(
        cheap_period_confirmed=True,
        ev_connected=True,
        observed_ev_connected=True,
        battery_soc=92,
        action="self_use",
        commands_permitted=True,
        active_session=False,
    )
    assert guard(**base) == 93.0
    assert guard(**{**base, "battery_soc": 99.8}) == 100.0
    assert guard(**{**base, "battery_soc": 101}) is None
    assert guard(**{**base, "battery_soc": None}) is None
    assert guard(**{**base, "battery_soc": float("nan")}) is None
    assert guard(**{**base, "cheap_period_confirmed": False}) is None
    assert guard(**{**base, "ev_connected": False}) is None
    assert guard(**{**base, "observed_ev_connected": None}) is None
    assert guard(**{**base, "action": "force_charge"}) is None
    assert guard(**{**base, "action": "force_discharge"}) is None
    assert guard(**{**base, "commands_permitted": False}) is None
    assert guard(**{**base, "active_session": True}) is None


def test_protection_is_read_back_before_self_use_and_failure_preserves_mode() -> None:
    backend = (ROOT / "foxess_control_backend.py").read_text(encoding="utf-8")
    start = backend.index("ev_restart_floor_target = _cheap_ev_restart_protective_floor(")
    readback = backend.index("ev_restart_floor_verified = bool(min_soc_ok)", start)
    select = backend.index('if min_soc_ok and decision.action == "self_use":', readback)
    assert start < readback < select
    assert "if ev_restart_floor_target is None or min_soc_ok:" in backend
    assert '"ev_restart_protective_floor_verified"' in backend


def test_initial_agile_publication_only_deferred_inside_coordinator_scan() -> None:
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    manager = (ROOT / "agile_smart_export.py").read_text(encoding="utf-8")
    assert "_kems_defer_initial_agile_publication = True" in coordinator
    assert "_kems_defer_initial_agile_publication = False" in coordinator
    assert 'getattr(self, "_kems_defer_initial_agile_publication", False)' in manager
    assert "self._publish(self._state)" in manager
    assert '"initial_publication_deferred_to_settlement"' in manager
    assert "coalesce_identical_settlement_publications(" in coordinator
    assert "post_shadow_settlement_changed" in coordinator


def test_live_soc_is_explicitly_physical_and_unknown_rates_stay_unknown() -> None:
    dashboard = (ROOT / "kems_master_dashboard.yaml").read_text(
        encoding="utf-8"
    )
    assert "name: FoxESS SOC (live)" in dashboard
    assert "title: Measured FoxESS battery SOC" in dashboard
    assert "Advisory KEMS simulation SOC" in dashboard
    assert "Missing half-hour prices remain unknown" in dashboard
    assert "if p.get('rate_pence') is not none else '—'" in dashboard
