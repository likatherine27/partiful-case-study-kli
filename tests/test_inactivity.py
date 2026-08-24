"""Tests for the proactive inactivity check-in / timeout logic in agent.py.

check_inactivity() never calls the Claude API — the "still there?" and
timeout messages are scripted, not generated — so these tests don't cost
anything. They monkeypatch the real 15-minute/5-minute thresholds down to
2 seconds so the suite runs in seconds instead of twenty minutes, while
exercising the exact same code path production uses.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from partiful_agent import config  # noqa: E402
from partiful_agent.agent import Agent  # noqa: E402
from partiful_agent.state import SessionOutcome  # noqa: E402

THRESHOLD = 2  # seconds — overrides the real 900/300 for fast tests
MARGIN = 0.3  # buffer past the threshold to absorb timing jitter


@pytest.fixture
def fast_thresholds(monkeypatch):
    monkeypatch.setattr(config, "INACTIVITY_PROMPT_SECONDS", THRESHOLD)
    monkeypatch.setattr(config, "INACTIVITY_TIMEOUT_SECONDS", THRESHOLD)


def test_no_prompt_before_threshold(fast_thresholds):
    agent = Agent()
    assert agent.check_inactivity() is None
    assert agent.state.outcome == SessionOutcome.IN_PROGRESS


def test_prompts_once_after_threshold(fast_thresholds):
    agent = Agent()
    time.sleep(THRESHOLD + MARGIN)

    message = agent.check_inactivity()

    assert message is not None
    assert "still there" in message.lower()
    assert agent.state.still_there_prompted_at is not None
    assert agent.state.outcome == SessionOutcome.IN_PROGRESS
    # It's also in the real transcript, so Claude has context if this resumes.
    assert agent.messages[-1] == {"role": "assistant", "content": message}


def test_does_not_reprompt_immediately(fast_thresholds):
    agent = Agent()
    time.sleep(THRESHOLD + MARGIN)
    agent.check_inactivity()

    assert agent.check_inactivity() is None


def test_times_out_after_no_reply_during_grace_period(fast_thresholds):
    agent = Agent()
    time.sleep(THRESHOLD + MARGIN)
    agent.check_inactivity()  # fires "are you still there?"

    time.sleep(THRESHOLD + MARGIN)
    message = agent.check_inactivity()  # grace period also elapsed

    assert message is not None
    assert "close" in message.lower()
    assert config.SUPPORT_EMAIL in message
    assert agent.state.outcome == SessionOutcome.TIMED_OUT


def test_reply_during_grace_period_resumes_normally(fast_thresholds):
    agent = Agent()
    time.sleep(THRESHOLD + MARGIN)
    agent.check_inactivity()
    assert agent.state.still_there_prompted_at is not None

    # record_activity() is exactly what send_user_message() calls first —
    # using it directly here avoids a real API call in this test.
    agent.state.record_activity()

    assert agent.state.still_there_prompted_at is None
    assert agent.state.outcome == SessionOutcome.IN_PROGRESS
    # Clock was reset, so it doesn't immediately fire again.
    assert agent.check_inactivity() is None


def test_a_terminal_session_is_left_alone(fast_thresholds):
    agent = Agent()
    agent.state.outcome = SessionOutcome.NUMBER_CHANGED
    time.sleep(THRESHOLD + MARGIN)

    assert agent.check_inactivity() is None
