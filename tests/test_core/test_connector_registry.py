"""Tests for connector registry auto-registration."""

from src.core.connectors import connector_registry


def test_google_connector_registered():
    """GoogleConnector should be auto-registered on import."""
    google = connector_registry.get("google")
    assert google is not None
    assert google.name == "google"


def test_registry_list_configured():
    """list_configured should return connectors whose env vars are set."""
    configured = connector_registry.list_configured()
    # In test env, google_client_id is not set → not in list
    assert isinstance(configured, list)


def test_registry_get_unknown():
    assert connector_registry.get("nonexistent") is None
