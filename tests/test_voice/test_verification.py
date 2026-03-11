"""Tests for voice SMS verification flow."""

from unittest.mock import AsyncMock, patch

from src.voice.verification import VoiceVerificationChallenge, voice_verification_store


async def test_create_verification_challenge_persists_to_redis():
    with (
        patch(
            "src.voice.verification.voice_verification_store._generate_code",
            return_value="123456",
        ),
        patch("src.voice.verification.redis.set", new_callable=AsyncMock) as mock_set,
    ):
        challenge = await voice_verification_store.create("call-123", "+15551234567")

    assert challenge == VoiceVerificationChallenge(
        call_id="call-123",
        phone_number="+15551234567",
        code="123456",
        attempts_remaining=3,
    )
    mock_set.assert_awaited_once()


async def test_verify_challenge_success_deletes_key():
    challenge = VoiceVerificationChallenge(
        call_id="call-123",
        phone_number="+15551234567",
        code="123456",
        attempts_remaining=2,
    )
    with (
        patch(
            "src.voice.verification.voice_verification_store.load",
            new_callable=AsyncMock,
            return_value=challenge,
        ),
        patch("src.voice.verification.redis.delete", new_callable=AsyncMock) as mock_delete,
    ):
        verified = await voice_verification_store.verify("call-123", "123456")

    assert verified is True
    mock_delete.assert_awaited_once()


async def test_verify_challenge_failure_decrements_attempts():
    challenge = VoiceVerificationChallenge(
        call_id="call-123",
        phone_number="+15551234567",
        code="123456",
        attempts_remaining=2,
    )
    with (
        patch(
            "src.voice.verification.voice_verification_store.load",
            new_callable=AsyncMock,
            return_value=challenge,
        ),
        patch("src.voice.verification.redis.set", new_callable=AsyncMock) as mock_set,
        patch("src.voice.verification.redis.delete", new_callable=AsyncMock) as mock_delete,
    ):
        verified = await voice_verification_store.verify("call-123", "000000")

    assert verified is False
    assert challenge.attempts_remaining == 1
    mock_set.assert_awaited_once()
    mock_delete.assert_not_awaited()
