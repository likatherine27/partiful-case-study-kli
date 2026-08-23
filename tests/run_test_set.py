"""Runs tests/test_cases.yaml as real conversations against the live Claude
API, using the exact same Agent class app.py uses — no UI, no mocking of
Claude itself (only Partiful's backend is mocked, per the assignment).

Each case is checked against ground truth the agent already tracks for
itself (state.outcome, the exact tool-call sequence) rather than fuzzy text
matching, so a pass means the actual flow and guardrails behaved correctly
in a real conversation — not just that a reply sounded plausible.

Usage:
    python3 tests/run_test_set.py                  # run every case
    python3 tests/run_test_set.py --verbose         # also print each turn/reply
    python3 tests/run_test_set.py self_serve_redirect happy_path_verified_and_changed
                                                     # run only these case IDs — each
                                                     # case is a handful of real API
                                                     # calls, so this is the cheap way
                                                     # to re-check one thing you're
                                                     # actively debugging instead of
                                                     # re-spending on all of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from partiful_agent.agent import Agent  # noqa: E402

CASES_FILE = Path(__file__).parent / "test_cases.yaml"


class CaseFailure(AssertionError):
    pass


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def run_case(case: dict, *, verbose: bool) -> Agent:
    agent = Agent()
    replies: list[str] = []

    try:
        _run_case_body(agent, case, replies, verbose=verbose)
    except CaseFailure as exc:
        # A failed case still made real API calls — attach the agent so
        # its cost still gets counted in the run total.
        exc.agent = agent
        raise
    return agent


def _run_case_body(agent: Agent, case: dict, replies: list[str], *, verbose: bool) -> None:
    for turn in case["turns"]:
        if verbose:
            print(f"    >>> {turn}")
        reply = agent.send_user_message(turn)
        replies.append(reply)
        if verbose:
            print(f"    <<< {reply}")

    state = agent.state

    if "expected_outcome" in case:
        _check(
            state.outcome.value == case["expected_outcome"],
            f"expected outcome '{case['expected_outcome']}', got '{state.outcome.value}'",
        )

    if "outcome_must_not_be" in case:
        _check(
            state.outcome.value != case["outcome_must_not_be"],
            f"outcome must not be '{case['outcome_must_not_be']}', but it was",
        )

    if "expected_actions" in case:
        _check(
            state.actions_taken == case["expected_actions"],
            f"expected actions {case['expected_actions']}, got {state.actions_taken}",
        )

    if "expected_account_locked" in case:
        locked = state.account.locked if state.account else None
        _check(
            locked == case["expected_account_locked"],
            f"expected account.locked={case['expected_account_locked']}, got {locked}",
        )

    if "final_reply_must_contain" in case:
        needle = case["final_reply_must_contain"].lower()
        _check(
            needle in replies[-1].lower(),
            f"expected final reply to contain '{needle}', got: {replies[-1]!r}",
        )

    if "first_reply_must_not_contain" in case:
        first = replies[0].lower()
        for forbidden in case["first_reply_must_not_contain"]:
            _check(
                forbidden.lower() not in first,
                f"first reply must not contain '{forbidden}', got: {replies[0]!r}",
            )

    return agent


def main() -> int:
    args = sys.argv[1:]
    verbose = "--verbose" in args
    only_ids = {a for a in args if not a.startswith("--")}

    cases = yaml.safe_load(CASES_FILE.read_text())
    if only_ids:
        cases = [c for c in cases if c["id"] in only_ids]
        missing = only_ids - {c["id"] for c in cases}
        if missing:
            print(f"Unknown case id(s), skipping: {', '.join(sorted(missing))}")

    passed, failed = 0, 0
    total_cost = 0.0
    for case in cases:
        label = case["id"]
        print(f"\n[{label}] {case.get('description', '').strip()}")
        try:
            agent = run_case(case, verbose=verbose)
        except CaseFailure as exc:
            print(f"  FAIL — {exc}")
            failed += 1
            total_cost += getattr(exc, "agent", None) and exc.agent.estimated_cost_usd() or 0.0
        else:
            print("  PASS")
            passed += 1
            total_cost += agent.estimated_cost_usd()

    total = passed + failed
    print(f"\n{'=' * 50}\n{passed}/{total} passed")
    print(f"Real cost of this run: ${total_cost:.4f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
