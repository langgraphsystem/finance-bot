"""Tests for synthetic voice simulation scenarios."""

from src.voice.simulations import builtin_voice_simulations, run_builtin_voice_simulations


def test_builtin_voice_simulations_pass():
    reports = run_builtin_voice_simulations()

    assert reports
    assert all(report.passed for report in reports)


def test_builtin_voice_simulations_include_expected_scenarios():
    scenario_ids = [scenario.scenario_id for scenario in builtin_voice_simulations()]

    assert "inbound_booking_success" in scenario_ids
    assert "sensitive_request_approval" in scenario_ids
    assert "realtime_failure" in scenario_ids
