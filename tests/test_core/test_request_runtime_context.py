from src.core.request_context import (
    get_current_correlation_id,
    get_current_release_enabled,
    get_current_release_flags,
    get_current_release_mode,
    get_current_request_id,
    get_current_rollout_bucket,
    get_current_rollout_cohort,
    get_current_shadow_enabled,
    reset_request_context,
    set_request_context,
    update_request_context,
)


def test_request_context_set_update_and_reset():
    token = set_request_context(
        request_id="req-1",
        correlation_id="corr-1",
    )
    try:
        assert get_current_request_id() == "req-1"
        assert get_current_correlation_id() == "corr-1"
        assert get_current_rollout_cohort() is None
        assert get_current_rollout_bucket() is None
        assert get_current_release_mode() is None

        update_request_context(
            rollout_cohort="internal",
            rollout_bucket=7,
            release_mode="internal",
            release_enabled=True,
            shadow_enabled=True,
            release_flags={"ff_post_gen_check": True},
        )

        assert get_current_rollout_cohort() == "internal"
        assert get_current_rollout_bucket() == 7
        assert get_current_release_mode() == "internal"
        assert get_current_release_enabled() is True
        assert get_current_shadow_enabled() is True
        assert get_current_release_flags() == {"ff_post_gen_check": True}
    finally:
        reset_request_context(token)

    assert get_current_request_id() is None
    assert get_current_correlation_id() is None
    assert get_current_rollout_cohort() is None
    assert get_current_rollout_bucket() is None
    assert get_current_release_mode() is None
    assert get_current_release_enabled() is None
    assert get_current_shadow_enabled() is None
    assert get_current_release_flags() is None
