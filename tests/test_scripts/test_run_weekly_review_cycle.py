import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.run_weekly_review_cycle import (
    apply_batch_review,
    build_batch_payload,
    fetch_review_selection,
    run_weekly_review_cycle,
    save_cycle_report,
)


def test_build_batch_payload_includes_selectors_and_labels():
    payload = build_batch_payload(
        reviewer="qa-1",
        notes="weekly review",
        labels=["weekly_review", "golden_replay"],
        selection_limit=150,
        max_selected=30,
        review_label="memory_failure",
        suggested_action="promote_to_dataset",
        suggested_final_label="memory_failure",
        tag="golden_replay",
        source="test_bot_live_golden_replay",
    )

    assert payload["trace_keys"] == []
    assert payload["reviewer"] == "qa-1"
    assert payload["labels"] == ["weekly_review", "golden_replay"]
    assert payload["selection_limit"] == 100
    assert payload["max_selected"] == 30
    assert payload["tag"] == "golden_replay"


async def test_fetch_review_selection_calls_review_queue_endpoint():
    response = MagicMock()
    response.json.return_value = {
        "selected_trace_key_count": 2,
        "selected_trace_keys": ["trace-1", "trace-2"],
    }
    response.raise_for_status = MagicMock()

    client_instance = AsyncMock()
    client_instance.get = AsyncMock(return_value=response)
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None

    with patch("scripts.run_weekly_review_cycle.httpx.AsyncClient", return_value=client_instance):
        snapshot = await fetch_review_selection(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
            limit=50,
            max_selected=25,
            review_label=None,
            suggested_action="promote_to_dataset",
            suggested_final_label=None,
            tag="golden_replay",
            source="test_bot_live_golden_replay",
        )

    assert snapshot["selected_trace_key_count"] == 2
    assert client_instance.get.await_args.kwargs["params"]["tag"] == "golden_replay"


async def test_apply_batch_review_posts_payload():
    response = MagicMock()
    response.json.return_value = {"applied_count": 2, "failed_count": 0}
    response.raise_for_status = MagicMock()

    client_instance = AsyncMock()
    client_instance.post = AsyncMock(return_value=response)
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None

    payload = {"reviewer": "qa-1", "trace_keys": []}
    with patch("scripts.run_weekly_review_cycle.httpx.AsyncClient", return_value=client_instance):
        result = await apply_batch_review(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
            payload=payload,
        )

    assert result["applied_count"] == 2
    assert client_instance.post.await_args.kwargs["json"] == payload


def test_save_cycle_report_writes_json(tmp_path: Path):
    report = {
        "reviewer": "qa-1",
        "selection": {"selected_trace_key_count": 2},
    }

    path = save_cycle_report(report, out_dir=tmp_path, prefix="weekly_review_cycle")

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["reviewer"] == "qa-1"


async def test_run_weekly_review_cycle_dry_run_skips_batch_apply(tmp_path: Path):
    selection = {
        "selected_trace_key_count": 2,
        "selected_trace_keys": ["trace-1", "trace-2"],
    }
    export_bundle = {
        "golden_dialogue_size": 3,
        "golden_dialogues": [{"trace_key": "corr-1"}],
        "weekly_curation": {
            "review_result_size": 5,
            "dataset_candidate_size": 3,
            "review_batch_size": 2,
            "feedback_size": 1,
        },
    }
    export_paths = {
        "summary": tmp_path / "summary.json",
        "weekly_snapshot": tmp_path / "weekly.json",
        "jsonl": tmp_path / "golden.jsonl",
    }
    for path in export_paths.values():
        path.write_text("{}", encoding="utf-8")

    with (
        patch(
            "scripts.run_weekly_review_cycle.fetch_review_selection",
            AsyncMock(return_value=selection),
        ),
        patch(
            "scripts.run_weekly_review_cycle.apply_batch_review",
            AsyncMock(),
        ) as mock_apply,
        patch(
            "scripts.run_weekly_review_cycle.fetch_ops_exports",
            AsyncMock(return_value=export_bundle),
        ),
        patch(
            "scripts.run_weekly_review_cycle.save_export_bundle",
            return_value=export_paths,
        ),
    ):
        result = await run_weekly_review_cycle(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
            reviewer="qa-1",
            apply=False,
            limit=50,
            selection_limit=100,
            max_selected=25,
            export_limit=100,
            notes="weekly review",
            labels=["weekly_review"],
            review_label=None,
            suggested_action="promote_to_dataset",
            suggested_final_label=None,
            tag="golden_replay",
            source="test_bot_live_golden_replay",
            out_dir=tmp_path,
            export_prefix="weekly_golden_dialogues",
            report_prefix="weekly_review_cycle",
        )

    assert result["report"]["batch_result"] is None
    assert result["report"]["selection"]["selected_trace_key_count"] == 2
    assert result["report"]["export_summary"]["feedback_size"] == 1
    mock_apply.assert_not_awaited()
