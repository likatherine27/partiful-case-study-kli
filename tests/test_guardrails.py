"""Unit tests for the security rules in state.py, via tools.py.

These never touch the network or the Claude API — they call execute_tool
directly, the same way agent.py would after Claude decides to call a tool.
That makes them fast, free, and fully deterministic, which is exactly what
you want for the rules that actually protect an account. The slower,
costlier end-to-end proof that a real conversation can't argue its way
around these rules lives in run_test_set.py instead.

Run with: pytest tests/test_guardrails.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from partiful_agent.mock_api import MockPartifulAPI
from partiful_agent.state import SessionOutcome, SessionState
from partiful_agent.tools import execute_tool

VALID_PHONE = "+15551234567"
OTHER_PHONE = "+15559876543"


def _fresh():
    return SessionState(), MockPartifulAPI(verbose=False)


def test_cannot_change_number_without_any_verification():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api)

    result = execute_tool(
        "update_phone_number", {"new_number": "+19998887777"}, state=state, api=api
    )

    assert result.startswith("BLOCKED")
    assert state.outcome != SessionOutcome.NUMBER_CHANGED
    assert api.calls[-1].name != "update_phone_number"


def test_cannot_change_number_without_account_lookup():
    state, api = _fresh()

    result = execute_tool(
        "update_phone_number", {"new_number": "+19998887777"}, state=state, api=api
    )

    assert result.startswith("BLOCKED")
    assert state.outcome != SessionOutcome.NUMBER_CHANGED


def test_successful_verification_allows_the_change():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api)
    execute_tool("verify_id", {"image_ref": "valid_id.jpg"}, state=state, api=api)

    result = execute_tool(
        "update_phone_number", {"new_number": "+19998887777"}, state=state, api=api
    )

    assert "changed" in result.lower()
    assert state.outcome == SessionOutcome.NUMBER_CHANGED
    assert any(c.name == "update_phone_number" for c in api.calls)


def test_three_failed_attempts_locks_the_account():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": OTHER_PHONE}, state=state, api=api)

    for bad_id in ["blurry_id.jpg", "expired_id.jpg", "mismatch_id.jpg"]:
        execute_tool("verify_id", {"image_ref": bad_id}, state=state, api=api)

    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED
    assert state.account.locked is True
    assert state.attempts_remaining == 0
    assert any(c.name == "lock_account" for c in api.calls)
    assert any(c.name == "send_warning_text" for c in api.calls)


def test_locked_account_rejects_further_id_attempts():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": OTHER_PHONE}, state=state, api=api)
    for bad_id in ["blurry_id.jpg", "expired_id.jpg", "mismatch_id.jpg"]:
        execute_tool("verify_id", {"image_ref": bad_id}, state=state, api=api)

    result = execute_tool(
        "verify_id", {"image_ref": "valid_id.jpg"}, state=state, api=api
    )

    assert result.startswith("BLOCKED")
    # Confirm no 4th verify_id call actually reached the mock backend.
    verify_calls = [c for c in api.calls if c.name == "verify_id"]
    assert len(verify_calls) == 3


def test_locked_account_also_rejects_a_number_change_attempt():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": OTHER_PHONE}, state=state, api=api)
    for bad_id in ["blurry_id.jpg", "expired_id.jpg", "mismatch_id.jpg"]:
        execute_tool("verify_id", {"image_ref": bad_id}, state=state, api=api)

    result = execute_tool(
        "update_phone_number", {"new_number": "+10005550000"}, state=state, api=api
    )

    assert result.startswith("BLOCKED")
    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED


def test_unknown_phone_number_finds_no_account():
    state, api = _fresh()
    result = execute_tool(
        "look_up_account", {"phone_number": "+19990000000"}, state=state, api=api
    )

    assert "no account found" in result.lower()
    assert state.account is None


def test_self_serve_never_touches_verification_state():
    state, api = _fresh()
    execute_tool("redirect_to_self_serve", {}, state=state, api=api)

    assert state.outcome == SessionOutcome.SELF_SERVE_REDIRECT
    assert state.id_verified is False
    assert state.account is None
    assert api.calls == []  # no backend action for a self-serve redirect


# --- Closing out the chat ----------------------------------------------------


def test_close_chat_after_self_serve_redirect_ends_the_chat():
    state, api = _fresh()
    execute_tool("redirect_to_self_serve", {}, state=state, api=api)
    assert not state.chat_has_ended  # "anything else?" hasn't happened yet

    result = execute_tool("close_chat", {}, state=state, api=api)

    assert not result.startswith("BLOCKED")
    assert state.chat_closed is True
    assert state.chat_has_ended
    # outcome itself is untouched — it still records WHAT happened.
    assert state.outcome == SessionOutcome.SELF_SERVE_REDIRECT


def test_number_changed_ends_the_chat_immediately_without_close_chat():
    # Unlike self-serve redirect, a completed number change ends the chat
    # on its own — no "anything else?" wrap-up, no close_chat call needed.
    # (The tool result here is instructions for the model, never shown to
    # the user directly — the live conversation test in test_cases.yaml
    # is what proves the actual reply doesn't ask "anything else?".)
    state, api = _verified_state()
    execute_tool(
        "update_phone_number", {"new_number": "+19998887777"}, state=state, api=api
    )

    assert state.chat_has_ended
    assert state.outcome == SessionOutcome.NUMBER_CHANGED

    # close_chat no longer applies here — the chat already ended.
    blocked = execute_tool("close_chat", {}, state=state, api=api)
    assert blocked.startswith("BLOCKED")


def test_close_chat_rejected_while_still_in_progress():
    state, api = _fresh()
    result = execute_tool("close_chat", {}, state=state, api=api)

    assert result.startswith("BLOCKED")
    assert not state.chat_has_ended


def test_close_chat_rejected_after_an_escalation():
    state, api = _fresh()
    execute_tool("escalate_unrelated_topic", {}, state=state, api=api)
    assert state.chat_has_ended  # already ended, via ends_chat this time

    result = execute_tool("close_chat", {}, state=state, api=api)
    assert result.startswith("BLOCKED")


# --- Unclear intent ---------------------------------------------------------


def test_unclear_intent_escalates_after_three_attempts():
    state, api = _fresh()
    for _ in range(2):
        result = execute_tool("record_unclear_intent", {}, state=state, api=api)
        assert "ask again" in result.lower()
        assert state.outcome == SessionOutcome.IN_PROGRESS

    result = execute_tool("record_unclear_intent", {}, state=state, api=api)
    assert "end the conversation" in result.lower()
    assert state.outcome == SessionOutcome.ESCALATED_UNCLEAR_INTENT


# --- Phone number normalization (not left to Claude's judgment) ------------


def test_bare_ten_digit_number_is_assumed_supported_region():
    state, api = _fresh()
    result = execute_tool(
        "look_up_account", {"phone_number": "9088093599"}, state=state, api=api
    )
    assert "found account" in result.lower()


def test_punctuated_number_is_normalized_before_validation():
    state, api = _fresh()
    for raw in ["908-809-3599", "(908) 809-3599", "19088093599"]:
        state, api = _fresh()
        result = execute_tool(
            "look_up_account", {"phone_number": raw}, state=state, api=api
        )
        assert "found account" in result.lower(), f"failed for input {raw!r}"


# --- Phone number validation (account lookup) -------------------------------


def test_malformed_phone_number_is_rejected_without_hitting_backend():
    state, api = _fresh()
    result = execute_tool(
        "look_up_account", {"phone_number": "12345"}, state=state, api=api
    )
    assert "valid phone number" in result.lower()
    assert state.phone_lookup_attempts == 1
    assert api.calls == []  # never reached the mock backend


def test_non_us_number_passes_format_validation_and_reaches_backend():
    # Regions outside the old US-only guardrail are no longer rejected
    # up front — a well-formed non-US number reaches the mock backend and
    # fails there (no matching account) rather than being turned away for
    # its region.
    state, api = _fresh()
    result = execute_tool(
        "look_up_account", {"phone_number": "+442071234567"}, state=state, api=api
    )
    assert "no account found" in result.lower()
    assert any(c.name == "look_up_account" for c in api.calls)
    assert state.phone_lookup_attempts == 1


def test_three_failed_lookups_escalates_and_stops():
    state, api = _fresh()
    for bad in ["12345", "+442071234567", "+19990000000"]:
        result = execute_tool(
            "look_up_account", {"phone_number": bad}, state=state, api=api
        )
    assert "end the conversation" in result.lower()
    assert state.outcome == SessionOutcome.ESCALATED_PHONE_LOOKUP_FAILED
    assert state.account is None


def test_valid_lookup_after_earlier_failures_still_succeeds():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": "12345"}, state=state, api=api)
    result = execute_tool(
        "look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api
    )
    assert "found account" in result.lower()
    assert state.account is not None
    assert state.outcome == SessionOutcome.IN_PROGRESS


# --- New number validation + collision --------------------------------------


def _verified_state():
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api)
    execute_tool("verify_id", {"image_ref": "valid_id.jpg"}, state=state, api=api)
    return state, api


def test_malformed_new_number_is_rejected_and_does_not_commit():
    state, api = _verified_state()
    result = execute_tool(
        "update_phone_number", {"new_number": "not-a-number"}, state=state, api=api
    )
    assert "valid phone number" in result.lower()
    assert state.new_number_attempts == 1
    assert state.outcome == SessionOutcome.IN_PROGRESS
    assert not any(c.name == "update_phone_number" for c in api.calls)


def test_three_failed_new_numbers_escalates_and_stops():
    state, api = _verified_state()
    for bad in ["nope", "+44207", "still-bad"]:
        result = execute_tool(
            "update_phone_number", {"new_number": bad}, state=state, api=api
        )
    assert "end the conversation" in result.lower()
    assert state.outcome == SessionOutcome.ESCALATED_NEW_NUMBER_FAILED


def test_new_number_already_on_another_account_is_a_collision():
    state, api = _verified_state()  # this account's number is VALID_PHONE
    result = execute_tool(
        "update_phone_number", {"new_number": OTHER_PHONE}, state=state, api=api
    )
    assert "already on another" in result.lower()
    assert state.outcome == SessionOutcome.ESCALATED_NUMBER_IN_USE
    # A collision is immediate — it must NOT consume a retry attempt.
    assert state.new_number_attempts == 0
    assert not any(c.name == "update_phone_number" for c in api.calls)


def test_new_number_success_after_one_bad_attempt():
    state, api = _verified_state()
    execute_tool("update_phone_number", {"new_number": "bad"}, state=state, api=api)
    result = execute_tool(
        "update_phone_number", {"new_number": "+19998887777"}, state=state, api=api
    )
    assert "changed" in result.lower()
    assert state.outcome == SessionOutcome.NUMBER_CHANGED


# --- Terminal sessions reject the new tools too -----------------------------


def test_ended_session_rejects_look_up_account():
    state, api = _fresh()
    for bad in ["12345", "+442071234567", "+19990000000"]:
        execute_tool("look_up_account", {"phone_number": bad}, state=state, api=api)
    assert state.outcome.is_terminal

    result = execute_tool(
        "look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api
    )
    assert result.startswith("BLOCKED")


def test_locked_account_cannot_be_redirected_to_self_serve():
    """Regression test: a session already ended (e.g. locked after 3
    failed ID attempts) must not be escapable by calling
    redirect_to_self_serve — found as a real gap, not hypothetical."""
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": OTHER_PHONE}, state=state, api=api)
    for bad_id in ["blurry_id.jpg", "expired_id.jpg", "mismatch_id.jpg"]:
        execute_tool("verify_id", {"image_ref": bad_id}, state=state, api=api)
    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED

    result = execute_tool("redirect_to_self_serve", {}, state=state, api=api)

    assert result.startswith("BLOCKED")
    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED
    assert state.account.locked is True


def test_retry_counters_survive_a_self_serve_flip_flop():
    """A user who fails 2 ID attempts, then flips to self-serve and back,
    must not get a fresh 3 attempts — the counter belongs to the session,
    not to whichever branch of the flow they're currently in."""
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api)
    execute_tool("verify_id", {"image_ref": "blurry_id.jpg"}, state=state, api=api)
    execute_tool("verify_id", {"image_ref": "expired_id.jpg"}, state=state, api=api)
    assert state.attempts_remaining == 1

    execute_tool("redirect_to_self_serve", {}, state=state, api=api)
    execute_tool("resume_after_self_serve_failure", {}, state=state, api=api)
    assert state.attempts_remaining == 1  # unchanged by the flip-flop

    result = execute_tool(
        "verify_id", {"image_ref": "mismatch_id.jpg"}, state=state, api=api
    )
    assert "0 attempts remaining" in result
    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED


def test_every_state_changing_tool_is_blocked_once_locked():
    """Exhaustive version of the redirect_to_self_serve regression test —
    checks every tool that can mutate session state, not just the one
    that happened to be reported."""
    state, api = _fresh()
    execute_tool("look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api)
    for bad_id in ["blurry_id.jpg", "expired_id.jpg", "mismatch_id.jpg"]:
        execute_tool("verify_id", {"image_ref": bad_id}, state=state, api=api)
    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED

    attempts = [
        ("redirect_to_self_serve", {}),
        ("resume_after_self_serve_failure", {}),
        ("escalate_no_id", {}),
        ("escalate_unrelated_topic", {}),
        ("close_chat", {}),
        ("verify_id", {"image_ref": "valid_id.jpg"}),
        ("update_phone_number", {"new_number": "+19998887777"}),
        ("look_up_account", {"phone_number": OTHER_PHONE}),
        ("record_unclear_intent", {}),
    ]
    for tool_name, args in attempts:
        result = execute_tool(tool_name, args, state=state, api=api)
        assert result.startswith("BLOCKED"), f"{tool_name} was not blocked"

    assert state.outcome == SessionOutcome.LOCKED_VERIFICATION_FAILED


def test_resume_after_self_serve_failure_reopens_the_session():
    state, api = _fresh()
    execute_tool("redirect_to_self_serve", {}, state=state, api=api)
    assert state.outcome.is_terminal

    result = execute_tool(
        "resume_after_self_serve_failure", {}, state=state, api=api
    )
    assert not result.startswith("BLOCKED")
    assert state.outcome == SessionOutcome.IN_PROGRESS

    # And the session is genuinely usable again afterward.
    lookup = execute_tool(
        "look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api
    )
    assert "found account" in lookup.lower()


def test_resume_after_self_serve_failure_rejected_without_a_prior_redirect():
    state, api = _fresh()
    result = execute_tool(
        "resume_after_self_serve_failure", {}, state=state, api=api
    )
    assert result.startswith("BLOCKED")
    assert state.outcome == SessionOutcome.IN_PROGRESS


def test_ended_session_rejects_record_unclear_intent():
    state, api = _fresh()
    for _ in range(3):
        execute_tool("record_unclear_intent", {}, state=state, api=api)
    assert state.outcome.is_terminal

    result = execute_tool("record_unclear_intent", {}, state=state, api=api)
    assert result.startswith("BLOCKED")


def test_unrelated_topic_escalates_immediately_and_ends_the_chat():
    state, api = _fresh()
    result = execute_tool("escalate_unrelated_topic", {}, state=state, api=api)

    assert "end the conversation" in result.lower()
    assert state.outcome == SessionOutcome.ESCALATED_UNRELATED_TOPIC
    assert state.outcome.ends_chat


# --- ends_chat: which outcomes should retire the chat input in app.py -------


def test_escalation_lockout_and_number_changed_outcomes_end_the_chat():
    for outcome in [
        SessionOutcome.NUMBER_CHANGED,
        SessionOutcome.LOCKED_VERIFICATION_FAILED,
        SessionOutcome.ESCALATED_NO_ID,
        SessionOutcome.ESCALATED_UNCLEAR_INTENT,
        SessionOutcome.ESCALATED_PHONE_LOOKUP_FAILED,
        SessionOutcome.ESCALATED_NEW_NUMBER_FAILED,
        SessionOutcome.ESCALATED_NUMBER_IN_USE,
        SessionOutcome.ESCALATED_UNRELATED_TOPIC,
        SessionOutcome.TIMED_OUT,
        SessionOutcome.TOOL_LOOP_EXHAUSTED,
    ]:
        assert outcome.ends_chat, f"{outcome} should end the chat"


def test_self_serve_redirect_does_not_end_the_chat_on_its_own():
    # The one outcome that's terminal for guardrail purposes (direct tool
    # calls are blocked) but still expects an "anything else?" exchange
    # before close_chat actually ends it — see chat_has_ended.
    assert not SessionOutcome.SELF_SERVE_REDIRECT.ends_chat


def test_in_progress_does_not_end_the_chat():
    assert not SessionOutcome.IN_PROGRESS.ends_chat


# --- execute_tool degrades instead of crashing on a bad call ----------------


def test_unknown_tool_name_returns_an_error_string():
    state, api = _fresh()
    result = execute_tool("not_a_real_tool", {}, state=state, api=api)
    assert result.startswith("Error:")


def test_missing_required_argument_returns_an_error_string_not_a_crash():
    # Nothing in TOOL_SCHEMAS can force Claude to include a required
    # argument — this is what happens if it calls verify_id without one.
    state, api = _fresh()
    result = execute_tool("verify_id", {}, state=state, api=api)
    assert result.startswith("Error:")


def test_unexpected_extra_argument_returns_an_error_string_not_a_crash():
    # Same idea in the other direction: additionalProperties: False in the
    # schema discourages this, but doesn't guarantee Claude never sends an
    # extra key — a handler crashing on that would silently kill the whole
    # turn and leave the user with no reply at all.
    state, api = _fresh()
    result = execute_tool(
        "verify_id",
        {"image_ref": "valid_id.jpg", "note": "unexpected"},
        state=state,
        api=api,
    )
    assert result.startswith("Error:")
    # And a well-formed call right after still works normally — the bad
    # call didn't leave the session in a broken state.
    result2 = execute_tool(
        "look_up_account", {"phone_number": VALID_PHONE}, state=state, api=api
    )
    assert "found account" in result2.lower()
