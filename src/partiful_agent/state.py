"""Session state and the security rules that depend on it.

This module is the reason the agent is trustworthy. The language model runs
the *conversation*; this file decides what is actually **allowed to happen**.
Every rule that protects an account lives here as ordinary Python, so no
amount of clever prompting by a user can talk the agent past it.

Nothing in here calls the model or the network, which makes it fast and
fully deterministic to unit-test.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from . import config


class SessionOutcome(str, Enum):
    """Where a conversation ended up.

    Subclassing `str` (a Python trick with no Java equivalent) means these
    compare and serialise as plain strings, which keeps the test-case YAML
    readable: `expected_outcome: number_changed`.
    """

    IN_PROGRESS = "in_progress"

    # Happy paths
    SELF_SERVE_REDIRECT = "self_serve_redirect"  # user still has the old phone
    NUMBER_CHANGED = "number_changed"  # ID verified, change committed

    # Terminal failure paths
    LOCKED_VERIFICATION_FAILED = "locked_verification_failed"  # 3 ID strikes
    ESCALATED_NO_ID = "escalated_no_id"  # user has no ID to submit
    ESCALATED_UNCLEAR_INTENT = "escalated_unclear_intent"  # 3 unclear replies
    ESCALATED_PHONE_LOOKUP_FAILED = "escalated_phone_lookup_failed"  # 3 bad lookups
    ESCALATED_NEW_NUMBER_FAILED = "escalated_new_number_failed"  # 3 bad new numbers
    ESCALATED_NUMBER_IN_USE = "escalated_number_in_use"  # new number taken elsewhere
    ESCALATED_UNRELATED_TOPIC = "escalated_unrelated_topic"  # not a phone-number request
    TIMED_OUT = "timed_out"  # user went quiet

    @property
    def is_terminal(self) -> bool:
        return self is not SessionOutcome.IN_PROGRESS

    @property
    def ends_chat(self) -> bool:
        """True for outcomes where no further reply is expected at all.

        Narrower than `is_terminal`: the two happy-path outcomes
        (SELF_SERVE_REDIRECT, NUMBER_CHANGED) are terminal for guardrail
        purposes — direct tool calls are blocked — but the flow still
        expects an "anything else?" exchange before the chat actually
        closes. The outcomes here are the ones prompts.py calls "stop and
        escalate" / "end the conversation": there is nothing left to say
        beyond the support-email instruction, so the UI can safely retire
        the input the moment one of these is reached.
        """
        return self in {
            SessionOutcome.LOCKED_VERIFICATION_FAILED,
            SessionOutcome.ESCALATED_NO_ID,
            SessionOutcome.ESCALATED_UNCLEAR_INTENT,
            SessionOutcome.ESCALATED_PHONE_LOOKUP_FAILED,
            SessionOutcome.ESCALATED_NEW_NUMBER_FAILED,
            SessionOutcome.ESCALATED_NUMBER_IN_USE,
            SessionOutcome.ESCALATED_UNRELATED_TOPIC,
            SessionOutcome.TIMED_OUT,
        }


@dataclass
class Account:
    """A Partiful account, as returned by the (mocked) internal lookup API.

    `@dataclass` generates the constructor, equals, and toString for us —
    roughly what Lombok's `@Data` does in Java.
    """

    account_id: str
    legal_name: str
    phone_number: str
    locked: bool = False


class GuardrailViolation(Exception):
    """Raised when the model tries to take an action the rules forbid.

    The message is written to be shown *back to the model*, so it can explain
    the refusal to the user in its own words instead of crashing the chat.
    """


@dataclass
class SessionState:
    """Everything we know about one support conversation.

    Deliberately *not* stored in the model's context: the model can forget,
    hallucinate, or be argued out of a number. This counter cannot.
    """

    account: Account | None = None
    id_attempts_used: int = 0
    id_verified: bool = False
    intent_clarification_attempts: int = 0
    phone_lookup_attempts: int = 0
    new_number_attempts: int = 0
    outcome: SessionOutcome = SessionOutcome.IN_PROGRESS

    # Inactivity tracking. `last_activity_at` starts ticking the moment a
    # session is created — a user who opens the chat and never says
    # anything eventually gets timed out too, same as one who goes quiet
    # mid-conversation. `still_there_prompted_at` is None until we've
    # actually asked "are you still there?" and are waiting on a reply.
    last_activity_at: float = field(default_factory=time.monotonic)
    still_there_prompted_at: float | None = None

    # Names of the mock API calls made, in order. The test suite asserts
    # against this to prove the right sequence of actions ran.
    actions_taken: list[str] = field(default_factory=list)

    # ---- Derived properties ----------------------------------------------

    @property
    def attempts_remaining(self) -> int:
        return max(0, config.MAX_ID_ATTEMPTS - self.id_attempts_used)

    @property
    def intent_clarification_attempts_remaining(self) -> int:
        return max(
            0,
            config.MAX_INTENT_CLARIFICATION_ATTEMPTS
            - self.intent_clarification_attempts,
        )

    @property
    def phone_lookup_attempts_remaining(self) -> int:
        return max(0, config.MAX_PHONE_LOOKUP_ATTEMPTS - self.phone_lookup_attempts)

    @property
    def new_number_attempts_remaining(self) -> int:
        return max(0, config.MAX_NEW_NUMBER_ATTEMPTS - self.new_number_attempts)

    @property
    def is_account_identified(self) -> bool:
        return self.account is not None

    @property
    def is_locked(self) -> bool:
        return self.account is not None and self.account.locked

    # ---- Guardrails -------------------------------------------------------
    #
    # Each `require_*` method either returns cleanly or raises
    # GuardrailViolation. Tools call these *before* touching the backend.

    def require_can_resume_after_self_serve_failure(self) -> None:
        if self.outcome != SessionOutcome.SELF_SERVE_REDIRECT:
            raise GuardrailViolation(
                "Can only resume this way immediately after a self-serve "
                "redirect — this session isn't in that state."
            )

    def require_session_open(self) -> None:
        """Shared by the newer tools that don't have their own dedicated
        guardrail: you can't do anything at all once a session has ended."""
        if self.outcome.is_terminal:
            raise GuardrailViolation("This session has already ended.")

    def require_can_verify_id(self) -> None:
        if self.outcome.is_terminal:
            raise GuardrailViolation(
                "This session has already ended and cannot verify further IDs."
            )
        if not self.is_account_identified:
            raise GuardrailViolation(
                "No account has been identified yet. Ask the user for the phone "
                "number currently on their account and look it up first."
            )
        if self.is_locked:
            raise GuardrailViolation(
                "This account is locked from automated changes. Direct the user "
                f"to email {config.SUPPORT_EMAIL}."
            )
        if self.attempts_remaining <= 0:
            raise GuardrailViolation(
                "The user has used all "
                f"{config.MAX_ID_ATTEMPTS} ID verification attempts."
            )

    def require_can_commit_change(self) -> None:
        """The single most important rule in the codebase.

        A phone number may only be changed after a *successful* ID
        verification against an identified account.
        """
        if self.outcome.is_terminal:
            raise GuardrailViolation("This session has already ended.")
        if not self.is_account_identified:
            raise GuardrailViolation(
                "No account has been identified. Look up the account first."
            )
        if self.is_locked:
            raise GuardrailViolation(
                "This account is locked from automated changes."
            )
        if not self.id_verified:
            raise GuardrailViolation(
                "Identity has NOT been verified for this account. You may not "
                "change the phone number. The user must pass ID verification "
                "first — there is no exception to this rule."
            )

    # ---- Mutations --------------------------------------------------------

    def record_id_attempt(self, *, passed: bool) -> None:
        """Consume one of the user's three attempts.

        The `*` forces `passed` to be given by name at the call site
        (`record_id_attempt(passed=True)`), so a bare `True` can never be
        misread as something else.
        """
        self.id_attempts_used += 1
        if passed:
            self.id_verified = True

    def resume_after_self_serve_failure(self) -> None:
        """Reopens a session that ended in a self-serve redirect, because
        the user came back saying that redirect didn't actually work for
        them. Only reachable via the guardrail above."""
        self.outcome = SessionOutcome.IN_PROGRESS

    def record_unclear_intent(self) -> None:
        """Call each time a response still doesn't clarify what the user
        needs. Caps out and ends the session after 3 unclear replies."""
        self.intent_clarification_attempts += 1
        if self.intent_clarification_attempts_remaining == 0:
            self.outcome = SessionOutcome.ESCALATED_UNCLEAR_INTENT

    def record_phone_lookup_attempt(self) -> None:
        """Call when a phone number fails for ANY reason — malformed, or
        well-formed but not found. All count toward the same cap."""
        self.phone_lookup_attempts += 1
        if self.phone_lookup_attempts_remaining == 0:
            self.outcome = SessionOutcome.ESCALATED_PHONE_LOOKUP_FAILED

    def record_new_number_attempt(self) -> None:
        """Call when a proposed new number fails format/region validation.
        A collision with an existing account is a separate, immediate
        terminal outcome — it does not consume one of these attempts."""
        self.new_number_attempts += 1
        if self.new_number_attempts_remaining == 0:
            self.outcome = SessionOutcome.ESCALATED_NEW_NUMBER_FAILED

    def record_activity(self) -> None:
        """Call whenever a real user message arrives. Resets the inactivity
        clock and resolves any pending "are you still there?" check-in —
        any reply at all counts as presence, not just a literal "yes"."""
        self.last_activity_at = time.monotonic()
        self.still_there_prompted_at = None

    def lock_account(self) -> None:
        if self.account is not None:
            self.account.locked = True
        self.outcome = SessionOutcome.LOCKED_VERIFICATION_FAILED

    def log_action(self, action: str) -> None:
        self.actions_taken.append(action)
