"""Tool definitions: the concrete actions Claude is allowed to take.

Each tool has two halves:
  - a JSON schema in TOOL_SCHEMAS (what Claude sees — its name, what it does,
    what arguments it takes)
  - a Python function below (what actually runs when Claude calls it)

Every function follows the same shape: check a guardrail if one applies,
call into mock_api.py for the fake backend action, update state.py, then
return a short string. That string becomes Claude's next piece of
information — it is never shown to the user directly.

agent.py is the only other file that touches this module: it reads
TOOL_SCHEMAS to tell Claude what's available, and calls `execute_tool` to
run whatever Claude decides to call.
"""

from __future__ import annotations

import re
from typing import Callable

from . import config
from .mock_api import MockPartifulAPI
from .state import GuardrailViolation, SessionOutcome, SessionState

# Supported numbers in E.164 form: the configured country code followed by
# 10 digits. Anything that still looks like a real international number
# gets a distinct "wrong region" message; anything else is "not a valid
# format" — both count toward the same retry limit, just with different
# wording so the user knows what to fix.
_SUPPORTED_PHONE_RE = re.compile(
    r"^\+" + re.escape(config.SUPPORTED_COUNTRY_CODE.lstrip("+")) + r"\d{10}$"
)
_INTERNATIONAL_LOOKING_RE = re.compile(r"^\+\d{8,15}$")


def _invalid_phone_reason(number: str) -> str | None:
    """None if the number is valid and in a supported region; otherwise a
    human-readable reason it was rejected."""
    if _SUPPORTED_PHONE_RE.match(number):
        return None
    if _INTERNATIONAL_LOOKING_RE.match(number):
        return (
            "That number appears to be outside a supported region — this "
            f"chat currently only supports {config.SUPPORTED_COUNTRY_CODE} "
            "phone numbers."
        )
    return (
        "That doesn't look like a valid phone number format "
        f"({config.SUPPORTED_COUNTRY_CODE} followed by 10 digits)."
    )

# ---- Schemas: what Claude sees ---------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "record_unclear_intent",
        "description": (
            "Call this each time the user's response still doesn't tell you "
            "what they need help with, AFTER you've already asked at least "
            "once. Do not call it for the very first vague message that "
            "prompted your first question. The result tells you whether to "
            "ask again or to stop and escalate."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "resume_after_self_serve_failure",
        "description": (
            "Call this when a user who was just redirected to self-serve "
            "says it didn't actually work for them. Reopens the session so "
            "you can proceed to look up their account and verify their ID, "
            "instead of the self-serve redirect being treated as final."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "look_up_account",
        "description": (
            "Look up the Partiful account currently associated with a phone "
            "number. Call this once the user says they don't have access to "
            "their old phone, using the number they say is on their account. "
            "The result tells you if it succeeded, and if not, whether to "
            "ask again or stop and escalate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "The phone number on the account, e.g. +15551234567.",
                }
            },
            "required": ["phone_number"],
        },
    },
    {
        "name": "redirect_to_self_serve",
        "description": (
            "Record that the user still has their old phone number and is "
            "being sent to change it themselves. Call this instead of doing "
            "any ID verification when the user confirms they have it."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_id",
        "description": (
            "Submit a photo of the user's government ID for verification "
            "against the account found by look_up_account. The result tells "
            "you whether it passed, why not if it failed, and how many "
            "attempts remain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_ref": {
                    "type": "string",
                    "description": "Reference to the uploaded ID image (e.g. a filename).",
                }
            },
            "required": ["image_ref"],
        },
    },
    {
        "name": "update_phone_number",
        "description": (
            "Attempt to commit the phone number change. Only succeeds if ID "
            "verification has already passed earlier in this session. The "
            "result tells you if it succeeded, and if not, whether the "
            "number was invalid (ask again), already belongs to another "
            "account (stop and escalate), or attempts are exhausted (stop "
            "and escalate)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "new_number": {
                    "type": "string",
                    "description": "The new phone number to put on the account.",
                }
            },
            "required": ["new_number"],
        },
    },
    {
        "name": "escalate_no_id",
        "description": (
            "Record that the user has no government ID at all to submit, and "
            "is being pointed to email support directly instead."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ---- Functions: what actually runs -----------------------------------------


def _record_unclear_intent(state: SessionState, api: MockPartifulAPI) -> str:
    try:
        state.require_session_open()
    except GuardrailViolation as exc:
        return f"BLOCKED: {exc}"

    state.record_unclear_intent()
    if state.intent_clarification_attempts_remaining == 0:
        return (
            "That was the 3rd unclear response in a row. Stop asking. Tell "
            "the user plainly that you're not able to tell what they need "
            f"help with, and they should email {config.SUPPORT_EMAIL} "
            "instead. End the conversation."
        )
    return (
        f"Still unclear. {state.intent_clarification_attempts_remaining} "
        "more attempt(s) before you should give up and escalate. Ask again "
        "— keep it neutral, don't mention phone numbers or this chat's scope."
    )


def _resume_after_self_serve_failure(
    state: SessionState, api: MockPartifulAPI
) -> str:
    try:
        state.require_can_resume_after_self_serve_failure()
    except GuardrailViolation as exc:
        return f"BLOCKED: {exc}"

    state.resume_after_self_serve_failure()
    return (
        "Session reopened. Proceed as if the user had said they don't have "
        "access to their old phone — ask for the phone number on their "
        "account next."
    )


def _look_up_account(
    state: SessionState, api: MockPartifulAPI, *, phone_number: str
) -> str:
    try:
        state.require_session_open()
    except GuardrailViolation as exc:
        return f"BLOCKED: {exc}"

    reason = _invalid_phone_reason(phone_number)
    if reason is None:
        account = api.look_up_account(phone_number)
        if account is not None:
            state.account = account
            return f"Found account for {account.legal_name}."
        reason = f"No account found for {phone_number}."

    state.record_phone_lookup_attempt()
    if state.phone_lookup_attempts_remaining == 0:
        return (
            f"{reason} That was the last of {config.MAX_PHONE_LOOKUP_ATTEMPTS} "
            "attempts. Stop asking. Tell the user plainly that you're unable "
            f"to locate their account and they should email "
            f"{config.SUPPORT_EMAIL} for help. End the conversation."
        )
    return (
        f"{reason} {state.phone_lookup_attempts_remaining} attempt(s) "
        "remaining. Ask them to double-check and give the number again."
    )


def _redirect_to_self_serve(state: SessionState, api: MockPartifulAPI) -> str:
    state.outcome = SessionOutcome.SELF_SERVE_REDIRECT
    return (
        "Recorded: user will self-serve. Tell them to log in and change it "
        f"from their profile page: {config.SELF_SERVE_HELP_URL}"
    )


def _verify_id(
    state: SessionState, api: MockPartifulAPI, *, image_ref: str
) -> str:
    try:
        state.require_can_verify_id()
    except GuardrailViolation as exc:
        return f"BLOCKED: {exc}"

    result = api.verify_id(image_ref=image_ref, account=state.account)
    state.record_id_attempt(passed=result.passed)

    if result.passed:
        return "Verification PASSED. You may now ask for the new phone number."

    if state.attempts_remaining == 0:
        api.lock_account(
            account=state.account, reason="3 failed ID verification attempts"
        )
        api.send_warning_text(to_number=state.account.phone_number)
        state.lock_account()
        return (
            f"Verification FAILED ({result.reason}). 0 attempts remaining — "
            "that was the last try. The account is now LOCKED from further "
            "automated changes, and a warning text has been sent to the "
            "number on file. Tell the user this plainly and seriously, and "
            f"that they can email {config.SUPPORT_EMAIL} themselves if they "
            "want a person to review it."
        )

    return (
        f"Verification FAILED ({result.reason}). "
        f"{state.attempts_remaining} attempt(s) remaining. Ask for another "
        "form of ID."
    )


def _update_phone_number(
    state: SessionState, api: MockPartifulAPI, *, new_number: str
) -> str:
    try:
        state.require_can_commit_change()
    except GuardrailViolation as exc:
        return f"BLOCKED: {exc}"

    reason = _invalid_phone_reason(new_number)
    if reason is None:
        # Reuse the same lookup the account-search step uses: if some OTHER
        # account already has this number, that's a collision, not a typo.
        existing = api.look_up_account(new_number)
        if existing is not None:
            state.outcome = SessionOutcome.ESCALATED_NUMBER_IN_USE
            return (
                f"That number is already on another Partiful account "
                f"({existing.legal_name}). This isn't something you can fix "
                "by trying a different number — tell the user plainly and "
                f"that they should email {config.SUPPORT_EMAIL} for help. "
                "End the conversation."
            )

        api.update_phone_number(account=state.account, new_number=new_number)
        api.send_confirmation_text(to_number=new_number)
        state.outcome = SessionOutcome.NUMBER_CHANGED
        return f"Phone number changed to {new_number}. A confirmation text was sent."

    state.record_new_number_attempt()
    if state.new_number_attempts_remaining == 0:
        return (
            f"{reason} That was the last of {config.MAX_NEW_NUMBER_ATTEMPTS} "
            "attempts. Stop asking. Tell the user plainly that you're unable "
            f"to complete the change and they should email "
            f"{config.SUPPORT_EMAIL} for help. End the conversation."
        )
    return (
        f"{reason} {state.new_number_attempts_remaining} attempt(s) "
        "remaining. Ask them to give the new number again."
    )


def _escalate_no_id(state: SessionState, api: MockPartifulAPI) -> str:
    state.outcome = SessionOutcome.ESCALATED_NO_ID
    return (
        f"Recorded: user has no ID. Tell them to email {config.SUPPORT_EMAIL} "
        "directly — this is a soft redirect, not a security warning."
    )


_HANDLERS: dict[str, Callable[..., str]] = {
    "record_unclear_intent": _record_unclear_intent,
    "resume_after_self_serve_failure": _resume_after_self_serve_failure,
    "look_up_account": _look_up_account,
    "redirect_to_self_serve": _redirect_to_self_serve,
    "verify_id": _verify_id,
    "update_phone_number": _update_phone_number,
    "escalate_no_id": _escalate_no_id,
}


def execute_tool(
    name: str, arguments: dict, *, state: SessionState, api: MockPartifulAPI
) -> str:
    """Run the tool Claude asked for and return the result as a string.

    This is the single entry point agent.py calls — it never needs to know
    which specific function backs which tool name.
    """
    state.log_action(name)
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Error: no such tool '{name}'."
    return handler(state, api, **arguments)
