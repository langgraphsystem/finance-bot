import uuid
from unittest.mock import AsyncMock, patch

from src.core.request_context import reset_request_context, set_request_context
from src.core.router import _run_intent_shadow_compare
from src.core.schemas.intent import IntentData, IntentDetectionResult


def _intent_result(intent: str, confidence: float = 0.9) -> IntentDetectionResult:
    return IntentDetectionResult(
        intent=intent,
        confidence=confidence,
        intent_type="action",
        data=IntentData(),
    )


async def test_shadow_compare_logs_mismatch_and_records_metric():
    token = set_request_context(
        request_id=str(uuid.uuid4()),
        correlation_id="corr-1",
        shadow_enabled=True,
    )
    try:
        with (
            patch(
                "src.core.router.detect_intent_v2",
                AsyncMock(return_value=_intent_result("set_reminder", 0.74)),
            ),
            patch("src.core.router.record_release_event", AsyncMock()) as mock_record,
            patch("src.core.router.log_runtime_event") as mock_log,
        ):
            await _run_intent_shadow_compare(
                primary_detector_name="detect_intent",
                detect_text="напомни завтра оплатить аренду",
                categories=[],
                language="ru",
                recent_context=None,
                primary_result=_intent_result("general_chat", 0.51),
            )
    finally:
        reset_request_context(token)

    mock_record.assert_awaited_once_with("shadow_mismatch_total")
    assert mock_log.call_args.args[2] == "intent_shadow_compared"
    assert mock_log.call_args.kwargs["intents_match"] is False


async def test_shadow_compare_skips_when_request_shadow_disabled():
    token = set_request_context(
        request_id=str(uuid.uuid4()),
        correlation_id="corr-2",
        shadow_enabled=False,
    )
    try:
        with (
            patch("src.core.router.detect_intent_v2", AsyncMock()) as mock_shadow,
            patch("src.core.router.record_release_event", AsyncMock()) as mock_record,
        ):
            await _run_intent_shadow_compare(
                primary_detector_name="detect_intent",
                detect_text="привет",
                categories=[],
                language="ru",
                recent_context=None,
                primary_result=_intent_result("general_chat"),
            )
    finally:
        reset_request_context(token)

    mock_shadow.assert_not_awaited()
    mock_record.assert_not_awaited()
