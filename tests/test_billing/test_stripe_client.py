"""Tests for Stripe client."""

from src.billing.stripe_client import StripeClient


def test_is_configured():
    client = StripeClient(secret_key="sk_test_123")
    assert client.is_configured


def test_not_configured():
    client = StripeClient(secret_key="")
    assert not client.is_configured


def test_verify_webhook_signature_rejects_empty():
    assert not StripeClient.verify_webhook_signature(
        payload=b"test", sig_header="", webhook_secret="whsec_test"
    )


def test_verify_webhook_signature_rejects_bad_format():
    assert not StripeClient.verify_webhook_signature(
        payload=b"test", sig_header="invalid", webhook_secret="whsec_test"
    )
