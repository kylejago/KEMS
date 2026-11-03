"""ROI rewards include only incremental, unsettled reward value."""

from kems_core import ROIState
from kems_core.roi_rewards import apply_reward_roi


def _roi():
    return ROIState(
        system_installed=True,
        actual_value_created_today_gbp=12.53,
        actual_value_created_total_gbp=385.68,
        net_investment_gbp=20995.0,
    )


def test_roi_defaults():
    assert ROIState().roi_rewards_unsettled_gbp == 0.0


def test_happy_hour_credit_counts_once_and_remains_unsettled():
    base = _roi()
    result = apply_reward_roi(
        base,
        {
            "total": 261.729143,
            "today": 0,
            "happy": 261.729143,
            "power_down": 0,
            "unsettled": 261.729143,
        },
    )
    assert result.actual_value_created_total_gbp == 388.30
    assert result.actual_roi_percent == 1.85
    assert result.happy_hour_roi_credit_gbp == 2.62
    assert result.roi_rewards_unsettled_gbp == 2.62
    assert base.actual_value_created_total_gbp == 385.68
