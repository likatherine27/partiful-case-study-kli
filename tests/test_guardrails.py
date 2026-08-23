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
