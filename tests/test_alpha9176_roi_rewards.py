"""ROI reward regression tests."""

from kems_core import ROIState


def test_roi_model_defaults():
    assert ROIState().roi_rewards_unsettled_gbp == 0.0
