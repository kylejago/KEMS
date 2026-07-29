from kems_core.config import MonitorConfig


def test_default_monitor_config() -> None:
    config = MonitorConfig()

    assert config.scan_interval == 300
    assert config.record_history is True
    assert config.learn_patterns is True
    assert config.advisor_enabled is False
    assert config.simulation_enabled is False
