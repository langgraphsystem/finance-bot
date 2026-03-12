import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.export_golden_dialogues import (
    build_headers,
    dialogues_to_jsonl,
    fetch_ops_exports,
    infer_base_url,
    save_export_bundle,
)


def test_infer_base_url_from_public_base_url():
    with patch.dict(
        "os.environ",
        {"PUBLIC_BASE_URL": "https://bot.example.com/", "TELEGRAM_WEBHOOK_URL": ""},
        clear=False,
    ):
        assert infer_base_url() == "https://bot.example.com"


def test_build_headers_returns_bearer_header():
    assert build_headers("secret") == {"Authorization": "Bearer secret"}
    assert build_headers("") == {}


def test_dialogues_to_jsonl_serializes_each_dialogue():
    dialogues = [
        {"trace_key": "corr-1", "input_text": "Привет"},
        {"trace_key": "corr-2", "input_text": "Пока"},
    ]
    lines = dialogues_to_jsonl(dialogues).splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["trace_key"] == "corr-1"
    assert json.loads(lines[1])["input_text"] == "Пока"


async def test_fetch_ops_exports_calls_expected_endpoints():
    golden_response = MagicMock()
    golden_response.json.return_value = {
        "golden_dialogues": [{"trace_key": "corr-1"}],
        "golden_dialogue_size": 1,
    }
    golden_response.raise_for_status = MagicMock()

    weekly_response = MagicMock()
    weekly_response.json.return_value = {
        "review_result_size": 1,
        "dataset_candidate_size": 1,
    }
    weekly_response.raise_for_status = MagicMock()

    client_instance = AsyncMock()
    client_instance.get = AsyncMock(side_effect=[golden_response, weekly_response])
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None

    with patch("scripts.export_golden_dialogues.httpx.AsyncClient", return_value=client_instance):
        bundle = await fetch_ops_exports(
            base_url="https://bot.example.com",
            limit=10,
            headers={"Authorization": "Bearer secret"},
        )

    assert bundle["golden_dialogue_size"] == 1
    assert bundle["golden_dialogues"][0]["trace_key"] == "corr-1"
    assert bundle["weekly_curation"]["dataset_candidate_size"] == 1
    assert client_instance.get.await_count == 2


def test_save_export_bundle_writes_json_and_jsonl(tmp_path: Path):
    bundle = {
        "exported_at": "2026-03-12T00:00:00",
        "base_url": "https://bot.example.com",
        "limit": 10,
        "golden_dialogues": [{"trace_key": "corr-1", "input_text": "Привет"}],
        "golden_dialogue_size": 1,
        "weekly_curation": {"review_result_size": 1},
    }

    paths = save_export_bundle(bundle, out_dir=tmp_path, prefix="golden")

    assert paths["summary"].exists()
    assert paths["weekly_snapshot"].exists()
    assert paths["jsonl"].exists()
    assert '"trace_key": "corr-1"' in paths["summary"].read_text(encoding="utf-8")
    assert "review_result_size" in paths["weekly_snapshot"].read_text(encoding="utf-8")
    assert '"trace_key": "corr-1"' in paths["jsonl"].read_text(encoding="utf-8")
