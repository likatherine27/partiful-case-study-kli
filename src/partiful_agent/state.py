"""Session state and the security rules that depend on it.

This module is the reason the agent is trustworthy. The language model runs
the *conversation*; this file decides what is actually **allowed to happen**.
Every rule that protects an account lives here as ordinary Python, so no
amount of clever prompting by a user can talk the agent past it.

Nothing in here calls the model or the network, which makes it fast and
fully deterministic to unit-test.
"""

from __future__ import annotations

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
    LOCKED_VERIFICATION_FAILED = "locked_verification_failed"  # 3 strikes
    ESCALATED_NO_ID = "escalated_no_id"  # user has no ID to submit
    TIMED_OUT = "timed_out"  # user went quiet

    @property
    def is_terminal(self) -> bool:
        return self is not SessionOutcome.IN_PROGRESS


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
    outcome: SessionOutcome = SessionOutcome.IN_PROGRESS

    # Names of the mock API calls made, in order. The test harness asserts
    # against this, and the UI renders it as a live action log.
    actions_taken: list[str] = field(default_factory=list)

    # ---- Derived properties ----------------------------------------------

    @property
    def attempts_remaining(self) -> int:
        return max(0, config.MAX_ID_ATTEMPTS - self.id_attempts_used)

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

    def lock_account(self) -> None:
        if self.account is not None:
            self.account.locked = True
        self.outcome = SessionOutcome.LOCKED_VERIFICATION_FAILED

    def log_action(self, action: str) -> None:
        self.actions_taken.append(action)
