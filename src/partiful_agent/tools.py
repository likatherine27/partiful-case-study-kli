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

from typing import Callable

from . import config
from .mock_api import MockPartifulAPI
from .state import GuardrailViolation, SessionOutcome, SessionState

# ---- Schemas: what Claude sees ---------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "look_up_account",
        "description": (
            "Look up the Partiful account currently associated with a phone "
            "number. Call this once the user says they don't have access to "
            "their old phone, using the number they say is on their account."
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
            "Commit the phone number change on the account. Only succeeds if "
            "ID verification has already passed earlier in this session."
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


def _look_up_account(
    state: SessionState, api: MockPartifulAPI, *, phone_number: str
) -> str:
    account = api.look_up_account(phone_number)
    if account is None:
        return (
            f"No account found for {phone_number}. Ask the user to "
            "double-check the number they gave you."
        )
    state.account = account
    return f"Found account for {account.legal_name}."


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

    api.update_phone_number(account=state.account, new_number=new_number)
    api.send_confirmation_text(to_number=new_number)
    state.outcome = SessionOutcome.NUMBER_CHANGED
    return f"Phone number changed to {new_number}. A confirmation text was sent."


def _escalate_no_id(state: SessionState, api: MockPartifulAPI) -> str:
    state.outcome = SessionOutcome.ESCALATED_NO_ID
    return (
        f"Recorded: user has no ID. Tell them to email {config.SUPPORT_EMAIL} "
        "directly — this is a soft redirect, not a security warning."
    )


_HANDLERS: dict[str, Callable[..., str]] = {
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
