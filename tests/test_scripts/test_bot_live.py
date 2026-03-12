import json

import pytest

from scripts.test_bot_live import load_golden_scenario_map, resolve_scenario_map


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
