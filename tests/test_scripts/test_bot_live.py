import json
from unittest.mock import AsyncMock, patch

import pytest

from scripts.test_bot_live import (
    TestResult,
    apply_reference_rubric,
    build_golden_mismatch_candidates,
    compute_stats,
    enqueue_golden_review_candidates,
    evaluate_reference_response,
    load_golden_scenario_map,
    resolve_scenario_map,
)


def test_load_golden_scenario_map_groups_by_scenario(tmp_path):
    golden_file = tmp_path / "golden.jsonl"
    golden_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trace_key": "corr-1",
                        "scenario": "memory_related",
                        "input_text": "Запомни мой бюджет",
                        "assistant_response": "Запомнил бюджет.",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "trace_key": "corr-2",
                        "scenario": "tool_failure",
                        "input_text": "Покажи письма от банка",
                        "assistant_response": "Не удалось получить почту.",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    scenario_map = load_golden_scenario_map(golden_file)

    assert list(scenario_map.keys()) == ["memory_related", "tool_failure"]
    assert scenario_map["memory_related"][0].trace_key == "corr-1"
    assert scenario_map["memory_related"][0].expected_response == "Запомнил бюджет."
    assert scenario_map["memory_related"][0].source == "golden"


def test_load_golden_scenario_map_filters_categories(tmp_path):
    golden_file = tmp_path / "golden.jsonl"
    golden_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {"scenario": "memory_related", "input_text": "Сообщение 1"},
                    ensure_ascii=False,
                ),
                json.dumps(
                    {"scenario": "tool_failure", "input_text": "Сообщение 2"},
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    scenario_map = load_golden_scenario_map(golden_file, categories=["tool_failure"])

    assert list(scenario_map.keys()) == ["tool_failure"]
    assert scenario_map["tool_failure"][0].text == "Сообщение 2"


def test_resolve_scenario_map_uses_builtin_defaults():
    categories, scenario_map = resolve_scenario_map(categories=["finance"])

    assert categories == ["finance"]
    assert scenario_map["finance"][0].category == "finance"
    assert scenario_map["finance"][0].expected_intent == "add_expense"


def test_load_golden_scenario_map_rejects_missing_input_text(tmp_path):
    golden_file = tmp_path / "golden.jsonl"
    golden_file.write_text(
        json.dumps({"scenario": "memory_related"}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing input_text"):
        load_golden_scenario_map(golden_file)


def test_evaluate_reference_response_marks_strong_match():
    rubric = evaluate_reference_response(
        "Запомнил бюджет и не буду слать уведомления после 21 00",
        "Хорошо, запомнил бюджет и не буду отправлять уведомления после 21:00.",
    )

    assert rubric.passed is True
    assert rubric.verdict == "strong_match"
    assert rubric.coverage >= 0.8


def test_apply_reference_rubric_downgrades_golden_mismatch():
    result = TestResult(
        category="memory_related",
        description="golden dialogue — memory_related",
        expected_intent="memory_related",
        message_sent="Запомни мой бюджет",
        response_text="Я не могу помочь с этим вопросом.",
        has_response=True,
        status="pass",
        expected_response_text="Запомнил бюджет и учту его дальше.",
        source="golden",
    )

    apply_reference_rubric(result, min_coverage=0.5)

    assert result.reference_rubric is not None
    assert result.reference_rubric.passed is False
    assert result.status == "error"
    assert "Reference mismatch" in result.error


def test_compute_stats_includes_reference_metrics():
    passed = TestResult(
        category="memory_related",
        description="golden ok",
        expected_intent="memory_related",
        message_sent="Запомни бюджет",
        response_text="Запомнил бюджет.",
        has_response=True,
        status="pass",
        expected_response_text="Запомнил бюджет.",
        source="golden",
    )
    failed = TestResult(
        category="tool_failure",
        description="golden fail",
        expected_intent="tool_failure",
        message_sent="Покажи почту",
        response_text="Не понимаю запрос.",
        has_response=True,
        status="pass",
        expected_response_text="Не удалось получить почту.",
        source="golden",
    )

    apply_reference_rubric(passed, min_coverage=0.5)
    apply_reference_rubric(failed, min_coverage=0.5)
    stats = compute_stats([passed, failed])

    assert stats.reference_evaluated == 2
    assert stats.reference_passed == 1
    assert stats.avg_reference_coverage > 0


def test_build_golden_mismatch_candidates_generates_replay_payload():
    result = TestResult(
        category="memory_related",
        description="golden dialogue — memory_related",
        expected_intent="memory_related",
        message_sent="Запомни мой бюджет",
        response_text="Я не могу помочь с этим вопросом.",
        has_response=True,
        status="pass",
        expected_response_text="Запомнил бюджет и учту его дальше.",
        source="golden",
        trace_key="corr-1",
    )
    apply_reference_rubric(result, min_coverage=0.5)

    candidates = build_golden_mismatch_candidates(
        [result],
        mode_key="telegram",
        run_timestamp="2026-03-12T10:00:00+00:00",
    )

    assert len(candidates) == 1
    result_index, payload = candidates[0]
    assert result_index == 0
    assert str(payload["trace_key"]).startswith("golden-replay:telegram:")
    assert payload["review_label"] == "memory_failure"
    assert payload["metadata"]["source_trace_key"] == "corr-1"


async def test_enqueue_golden_review_candidates_uses_local_ingest_for_direct_mode():
    candidates = [
        (
            0,
            {
                "trace_key": "golden-replay:direct:abc",
                "review_label": "wrong_route",
                "outcome": "wrong_route",
                "tags": ["golden_replay"],
            },
        )
    ]
    with patch(
        "src.core.conversation_analytics.ingest_review_trace",
        AsyncMock(return_value={"trace_key": "golden-replay:direct:abc"}),
    ):
        results = await enqueue_golden_review_candidates(
            candidates,
            mode_key="direct",
            ops_base_url="http://localhost:8000",
            health_secret="",
        )

    assert results == [(0, True, "golden-replay:direct:abc", None)]
