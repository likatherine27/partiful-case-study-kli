"""The conversation loop.

This file is deliberately generic — it has no idea what a phone number is.
Its only job is the mechanics of talking to Claude: send the conversation,
notice whether Claude wants to call a tool or just reply with text, run
the tool via tools.py, feed the result back, and repeat until Claude
produces a plain-text answer.

Everything specific to THIS project — the flow, the tone, what actions
exist — lives in prompts.py and tools.py, not here.
"""

from __future__ import annotations

import time

import anthropic
from dotenv import load_dotenv

from . import config
from .mock_api import MockPartifulAPI
from .prompts import SYSTEM_PROMPT
from .state import SessionOutcome, SessionState
from .tools import TOOL_SCHEMAS, execute_tool

load_dotenv()


class Agent:
    """One customer's support conversation, start to finish.

    An Agent owns everything a session needs: the Claude client, the
    conversation transcript, and the SessionState/MockPartifulAPI pair that
    tools.py reads and writes. Create a new Agent per conversation — nothing
    here is meant to be shared across users.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()
        self.state = SessionState()
        self.api = MockPartifulAPI()
        # The running transcript, in the shape Claude's API expects: a list
        # of {"role": ..., "content": ...} dicts, alternating user/assistant.
        self.messages: list[dict] = []
        # Raw token counts across every real API call this Agent has made.
        # Used only to report actual spend (see run_test_set.py) — this is
        # a development-cost visibility tool, not something end users see.
        self.usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

    def estimated_cost_usd(self) -> float:
        """Real spend for this Agent's calls so far, from accumulated
        token counts and config's pricing constants — not an estimate of
        token count, an estimate of dollars from exact token counts."""
        u = self.usage
        return (
            u["input_tokens"] * config.PRICE_PER_MILLION_INPUT_TOKENS
            + u["output_tokens"] * config.PRICE_PER_MILLION_OUTPUT_TOKENS
            + u["cache_creation_input_tokens"]
            * config.PRICE_PER_MILLION_CACHE_WRITE_TOKENS
            + u["cache_read_input_tokens"]
            * config.PRICE_PER_MILLION_CACHE_READ_TOKENS
        ) / 1_000_000

    def send_user_message(self, text: str) -> str:
        """Send one user turn and return Claude's eventual text reply.

        If Claude needs to call tools first, that all happens inside this
        call — the caller only sees the final text, once Claude is done
        acting and ready to speak.
        """
        self.state.record_activity()
        self.messages.append({"role": "user", "content": text})
        return self._run_until_text_reply()

    def check_inactivity(self) -> str | None:
        """Call this periodically, independent of user input, to notice a
        quiet user. Unlike everything else in this file, this doesn't call
        Claude at all — "are you still there?" and the eventual timeout
        message are both scripted, not generated, since they're a
        mechanical clock check rather than something needing judgment.

        Returns the new message to show if something just happened (the
        check-in or the timeout), or None if there's nothing to do yet.
        Whatever it returns is also appended to `self.messages`, so if the
        conversation resumes, Claude has full context that this happened.
        """
        if self.state.outcome.is_terminal:
            return None

        now = time.monotonic()

        if self.state.still_there_prompted_at is None:
            if now - self.state.last_activity_at < config.INACTIVITY_PROMPT_SECONDS:
                return None
            self.state.still_there_prompted_at = now
            message = "Hey, just checking — are you still there?"
            self.messages.append({"role": "assistant", "content": message})
            return message

        if now - self.state.still_there_prompted_at < config.INACTIVITY_TIMEOUT_SECONDS:
            return None

        self.state.outcome = SessionOutcome.TIMED_OUT
        message = (
            "Since I haven't heard back, I'm going to close this chat out. "
            "Feel free to start a new one anytime, or email "
            f"{config.SUPPORT_EMAIL} if you still need help."
        )
        self.messages.append({"role": "assistant", "content": message})
        return message

    # Shown whenever Claude doesn't produce something usable — an API
    # failure, or a reply with neither text nor a tool call. Deliberately
    # doesn't end the session: unlike TOOL_LOOP_EXHAUSTED (the model
    # genuinely couldn't resolve the turn after several tries), this is a
    # one-off hiccup, so the user should just be able to try again.
    _COULD_NOT_PROCESS_REPLY = "Sorry, I couldn't quite catch that — could you try again?"

    def _run_until_text_reply(self) -> str:
        for _ in range(config.MAX_TOOL_ITERATIONS):
            try:
                response = self._client.messages.create(
                    model=config.MODEL,
                    max_tokens=config.MAX_TOKENS,
                    # cache_control marks a breakpoint: everything up through
                    # this block (the tool schemas, then this system prompt —
                    # both fully static) gets cached instead of re-billed at
                    # full price on every single call. Only the growing
                    # `messages` list below is ever actually new.
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=TOOL_SCHEMAS,
                    messages=self.messages,
                )
            except anthropic.AnthropicError:
                # A network blip, rate limit, timeout, etc. — nothing was
                # recorded for this turn, so append the fallback as the
                # assistant's reply to keep the transcript's roles
                # alternating for whatever the user sends next.
                self.messages.append(
                    {"role": "assistant", "content": self._COULD_NOT_PROCESS_REPLY}
                )
                return self._COULD_NOT_PROCESS_REPLY

            self.usage["input_tokens"] += response.usage.input_tokens
            self.usage["output_tokens"] += response.usage.output_tokens
            self.usage["cache_creation_input_tokens"] += (
                response.usage.cache_creation_input_tokens or 0
            )
            self.usage["cache_read_input_tokens"] += (
                response.usage.cache_read_input_tokens or 0
            )
            self.messages.append({"role": "assistant", "content": response.content})

            tool_uses = [
                block for block in response.content if block.type == "tool_use"
            ]
            if not tool_uses:
                # Normally plain text — Claude decided to just reply. On the
                # rare turn where it produces neither a tool call nor any
                # text at all, showing that blank string would look exactly
                # like the chat silently breaking, so fall back instead.
                return self._extract_text(response.content) or self._COULD_NOT_PROCESS_REPLY

            self.messages.append(
                {"role": "user", "content": self._run_tools(tool_uses)}
            )

        # Claude never settled on a text reply within the iteration budget.
        # This message tells the user we're done here, so the session
        # needs to actually end here too — otherwise the chat input stays
        # open with no "Start a new chat" button, same bug as every other
        # ending path in this file.
        self.state.outcome = SessionOutcome.TOOL_LOOP_EXHAUSTED
        return (
            "Sorry, something went wrong on my end handling that. "
            f"Please email {config.SUPPORT_EMAIL} and we'll take it from here."
        )

    def _run_tools(self, tool_uses: list) -> list[dict]:
        """Execute every tool Claude asked for and package the results.

        Claude can request more than one tool call in a single turn; each
        needs its own tool_result block, matched back by `tool_use_id`.
        """
        results = []
        for block in tool_uses:
            result_text = execute_tool(
                block.name, block.input, state=self.state, api=self.api
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                }
            )
        return results

    @staticmethod
    def _extract_text(content_blocks: list) -> str:
        return "".join(
            block.text for block in content_blocks if block.type == "text"
        )
