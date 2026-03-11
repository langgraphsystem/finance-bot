from src.core.request_context import (
    get_current_correlation_id,
    get_current_release_flags,
    get_current_request_id,
    get_current_rollout_cohort,
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

        update_request_context(
            rollout_cohort="internal",
            release_flags={"ff_post_gen_check": True},
        )

        assert get_current_rollout_cohort() == "internal"
        assert get_current_release_flags() == {"ff_post_gen_check": True}
    finally:
        reset_request_context(token)

    assert get_current_request_id() is None
    assert get_current_correlation_id() is None
    assert get_current_rollout_cohort() is None
    assert get_current_release_flags() is None
