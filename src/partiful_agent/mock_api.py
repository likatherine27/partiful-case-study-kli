"""Stand-in for Partiful's internal APIs.

This project has no access to Partiful's real internal services, so
**every** side effect the agent can cause is funnelled through this one class
and printed as `[API CALL] ...` instead of actually executed. Swapping in
the real backend means editing this file and nothing else.

Calls are also recorded in `self.calls`, which is what the test suite
asserts against to prove the right sequence of actions ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import Account


@dataclass
class RecordedCall:
    """One internal-API action the agent took."""

    name: str
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
        return f"{self.name}({args})"


@dataclass
class VerificationResult:
    passed: bool
    reason: str


# --- Seeded fake data ------------------------------------------------------
#
# A tiny fake account directory so the agent has something to look up.
# Keyed by the phone number currently on the account.

_SEED_ACCOUNTS: dict[str, Account] = {
    "+15551234567": Account(
        account_id="acct_001",
        legal_name="Jordan Rivera",
        phone_number="+15551234567",
    ),
    "+15559876543": Account(
        account_id="acct_002",
        legal_name="Sam Chen",
        phone_number="+15559876543",
    ),
    "+19088093599": Account(
        account_id="acct_003",
        legal_name="Katherine Li",
        phone_number="+19088093599",
    ),
    "+11234567890": Account(
        account_id="acct_004",
        legal_name="Sample User",
        phone_number="+11234567890",
    ),
}

# --- Deterministic ID-verification stub ------------------------------------
#
# Real verification would call a vendor (Persona, Stripe Identity, Onfido) or
# an internal service. This stub keys off the uploaded file's NAME instead,
# so the same fixture always produces the same result — a deliberate
# simplification for a fast, fully repeatable test suite.

_ID_FIXTURES: dict[str, VerificationResult] = {
    "valid_id": VerificationResult(
        True, "Document authentic; name matches the name on the account."
    ),
    "blurry_id": VerificationResult(
        False, "Image quality too low to read the document."
    ),
    "expired_id": VerificationResult(
        False, "Document is past its expiration date."
    ),
    "mismatch_id": VerificationResult(
        False, "Document is authentic but the name does not match the account."
    ),
}


class MockPartifulAPI:
    """Fake internal API surface.

    An instance is created per session and passed into the tools, rather than
    using module-level functions. That keeps tests isolated from each other —
    no shared global state to reset between runs.
    """

    def __init__(self, *, verbose: bool = True) -> None:
        self.calls: list[RecordedCall] = []
        self._verbose = verbose
        # Fresh copies so one session can't mutate another's accounts.
        self._accounts = {
            number: Account(**vars(account))
            for number, account in _SEED_ACCOUNTS.items()
        }

    def _record(self, name: str, **details: object) -> None:
        call = RecordedCall(name=name, details=details)
        self.calls.append(call)
        if self._verbose:
            print(f"[API CALL] {call}")

    # ---- Read operations --------------------------------------------------

    def look_up_account(self, phone_number: str) -> Account | None:
        """Find the account currently attached to `phone_number`."""
        self._record("look_up_account", phone_number=phone_number)
        return self._accounts.get(phone_number)

    def verify_id(self, *, image_ref: str, account: Account) -> VerificationResult:
        """Submit an ID document for verification against an account."""
        self._record(
            "verify_id", image_ref=image_ref, account_id=account.account_id
        )
        for fixture_name, result in _ID_FIXTURES.items():
            if fixture_name in image_ref.lower():
                return result
        return VerificationResult(
            False, "Document could not be recognised as a valid government ID."
        )

    # ---- Write operations -------------------------------------------------

    def update_phone_number(self, *, account: Account, new_number: str) -> None:
        """THE consequential action: commit the phone number change."""
        self._record(
            "update_phone_number",
            account_id=account.account_id,
            old_number=account.phone_number,
            new_number=new_number,
        )
        account.phone_number = new_number

    def send_confirmation_text(self, *, to_number: str) -> None:
        self._record("send_confirmation_text", to_number=to_number)

    def send_warning_text(self, *, to_number: str) -> None:
        """Warn the number on file that someone tried to take over the account.

        Deliberately a text and not an email: an account may not have an email
        address attached, but by definition it always has a phone number.
        """
        self._record("send_warning_text", to_number=to_number)

    def lock_account(self, *, account: Account, reason: str) -> None:
        self._record(
            "lock_account", account_id=account.account_id, reason=reason
        )
        account.locked = True
