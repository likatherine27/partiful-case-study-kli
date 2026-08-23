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

import anthropic
from dotenv import load_dotenv

from . import config
from .mock_api import MockPartifulAPI
from .prompts import SYSTEM_PROMPT
from .state import SessionState
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

    def send_user_message(self, text: str) -> str:
        """Send one user turn and return Claude's eventual text reply.

        If Claude needs to call tools first, that all happens inside this
        call — the caller only sees the final text, once Claude is done
        acting and ready to speak.
        """
        self.messages.append({"role": "user", "content": text})
        return self._run_until_text_reply()

    def _run_until_text_reply(self) -> str:
        for _ in range(config.MAX_TOOL_ITERATIONS):
            response = self._client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            tool_uses = [
                block for block in response.content if block.type == "tool_use"
            ]
            if not tool_uses:
                return self._extract_text(response.content)

            self.messages.append(
                {"role": "user", "content": self._run_tools(tool_uses)}
            )

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
