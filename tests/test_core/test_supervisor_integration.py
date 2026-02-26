"""Tests for the supervisor routing integration with the router pipeline."""

from unittest.mock import patch

from src.core.intent import detect_intent, detect_intent_v2


def test_get_intent_detector_default():
    """Default (flag off) should return detect_intent."""
    from src.core.config import settings
    from src.core.router import _get_intent_detector

    with patch.object(settings, "ff_supervisor_routing", False):
        detector = _get_intent_detector()
        assert detector is detect_intent


def test_get_intent_detector_supervisor():
    """With flag on, should return detect_intent_v2."""
    from src.core.config import settings
    from src.core.router import _get_intent_detector

    with patch.object(settings, "ff_supervisor_routing", True):
        detector = _get_intent_detector()
        assert detector is detect_intent_v2


def test_detect_intent_v2_function_signature():
    """detect_intent_v2 should accept the same params as detect_intent."""
    import inspect

    v1_params = set(inspect.signature(detect_intent).parameters.keys())
    v2_params = set(inspect.signature(detect_intent_v2).parameters.keys())

    # v2 must accept all params that v1 accepts
    assert v1_params.issubset(v2_params), (
        f"detect_intent_v2 missing params: {v1_params - v2_params}"
    )


def test_scoped_defs_total_skill_count():
    """Total skills in SCOPED_INTENT_DEFS should match the catalog."""
    from src.core.intent import SCOPED_INTENT_DEFS

    total = sum(len(defs) for defs in SCOPED_INTENT_DEFS.values())
    # Should have at least 68 skills (matching the registry)
    assert total >= 68, f"Only {total} skills in SCOPED_INTENT_DEFS, expected >= 68"


def test_feature_flag_exists():
    """Feature flag ff_supervisor_routing should exist in Settings."""
    from src.core.config import Settings

    # Check the field exists with correct default
    fields = Settings.model_fields
    assert "ff_supervisor_routing" in fields
    assert fields["ff_supervisor_routing"].default is False
