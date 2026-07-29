from datetime import datetime

from kems_core.models import MissionAction, MissionPlan, MissionStep


def test_add_mission_step() -> None:
    """Mission steps should be stored."""

    plan = MissionPlan(created=datetime.now())

    step = MissionStep(
        start=datetime.now(),
        end=datetime.now(),
        action=MissionAction.CHARGE,
        target_power_kw=5.0,
        reason="Unit test",
    )

    plan.add_step(step)

    assert len(plan.steps) == 1
