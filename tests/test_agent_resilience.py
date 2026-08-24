"""Tests for how agent.py degrades when talking to Claude goes wrong.

Unlike the rest of the suite (which deliberately never mocks Claude's
conversational behavior — see run_test_set.py), these mock the API client
itself. That's a different concern: not "did the model make the right
call," but "does a network blip, rate limit, or a genuinely empty
response leave the user with a real reply instead of the chat silently
going dead." There's no way to force those conditions against the real
API on demand, so mocking the client is the only way to test them at all.

Run with: pytest tests/test_agent_resilience.py -v
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from partiful_agent.agent import Agent  # noqa: E402

FALLBACK = "Sorry, I couldn't quite catch that — could you try again?"


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


def _fake_response(content: list) -> SimpleNamespace:
    return SimpleNamespace(content=content, usage=_FakeUsage())


def test_api_failure_gets_a_friendly_reply_not_a_crash():
    agent = Agent()

    def broken_create(*args, **kwargs):
        raise anthropic.APIConnectionError(request=None)

    agent._client.messages.create = broken_create

    reply = agent.send_user_message("Hi, I need to change my phone number.")

    assert reply == FALLBACK
    # Doesn't end the session — this is a one-off hiccup, not a reason to
    # give up on the whole conversation.
    assert not agent.state.chat_has_ended


def test_api_failure_keeps_the_transcript_alternating():
    # If the fallback isn't recorded as the assistant's turn, the next
    # real call sends two consecutive user messages, which the API
    # rejects — silently breaking the *next* message too.
    agent = Agent()
    agent._client.messages.create = lambda *a, **k: (_ for _ in ()).throw(
        anthropic.APIConnectionError(request=None)
    )

    agent.send_user_message("Hi, I need to change my phone number.")

    roles = [m["role"] for m in agent.messages]
    assert roles == ["user", "assistant"]
    assert agent.messages[-1] == {"role": "assistant", "content": FALLBACK}


def test_response_with_no_text_and_no_tool_call_gets_a_friendly_reply():
    # An edge case, not a crash: Claude's turn ends with nothing usable
    # at all (e.g. a stray non-text content block). Showing that blank
    # string would look exactly like the chat silently breaking.
    agent = Agent()
    agent._client.messages.create = lambda *a, **k: _fake_response(
        [SimpleNamespace(type="redacted_thinking")]
    )

    reply = agent.send_user_message("Hi, I need to change my phone number.")

    assert reply == FALLBACK
    assert not agent.state.chat_has_ended


def test_normal_text_reply_is_unaffected():
    # Guards against the fallback swallowing legitimate short replies.
    agent = Agent()
    agent._client.messages.create = lambda *a, **k: _fake_response(
        [SimpleNamespace(type="text", text="Hey! What can I help you with?")]
    )

    reply = agent.send_user_message("hi")

    assert reply == "Hey! What can I help you with?"
