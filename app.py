"""Streamlit chat UI for the Partiful phone-number-change agent.

This file only renders. It holds no business logic of its own — every
decision (what to say, what tool to call, whether an action is allowed)
happens inside agent.py / tools.py / state.py. That split is what lets
tests/run_test_set.py drive the exact same Agent class with no UI at all,
so the demo and the automated tests exercise identical code.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from partiful_agent.agent import Agent  # noqa: E402
from partiful_agent.state import SessionOutcome  # noqa: E402

st.set_page_config(page_title="Partiful Support", page_icon="📱")


def new_agent() -> Agent:
    return Agent()


if "agent" not in st.session_state:
    st.session_state.agent = new_agent()
    st.session_state.display_messages = []  # [(role, text), ...]
    st.session_state.processed_upload = None

agent: Agent = st.session_state.agent

# ---- Sidebar: session status + the live internal-API action log -----------

with st.sidebar:
    st.subheader("Session status")
    st.write(f"**Outcome:** `{agent.state.outcome.value}`")
    if agent.state.account:
        st.write(f"**Account:** {agent.state.account.legal_name}")
        st.write(f"**Locked:** {agent.state.account.locked}")
    st.write(f"**ID attempts used:** {agent.state.id_attempts_used} / 3")

    st.subheader("Internal API activity")
    st.caption(
        "Partiful's real backend isn't available for this project — every "
        "action below is printed here instead of actually being called."
    )
    if agent.api.calls:
        st.code(
            "\n".join(f"[{i + 1}] {c}" for i, c in enumerate(agent.api.calls)),
            language=None,
        )
    else:
        st.caption("No backend actions yet.")

    st.divider()
    if st.button("Start new chat", use_container_width=True):
        st.session_state.agent = new_agent()
        st.session_state.display_messages = []
        st.session_state.processed_upload = None
        st.rerun()

# ---- Main chat area ---------------------------------------------------------

st.title("Partiful Support")
st.caption("Change the phone number on your account")

_BANNER = {
    SessionOutcome.SELF_SERVE_REDIRECT: (
        "info",
        "Session ended: redirected to self-serve.",
    ),
    SessionOutcome.NUMBER_CHANGED: ("success", "Session ended: number changed."),
    SessionOutcome.LOCKED_VERIFICATION_FAILED: (
        "error",
        "Session ended: account locked after 3 failed ID attempts.",
    ),
    SessionOutcome.ESCALATED_NO_ID: (
        "warning",
        "Session ended: user has no ID, pointed to email support.",
    ),
}
if agent.state.outcome in _BANNER:
    kind, message = _BANNER[agent.state.outcome]
    getattr(st, kind)(message)

for role, text in st.session_state.display_messages:
    with st.chat_message(role):
        st.write(text)


def _send_turn(user_text: str) -> None:
    """Send one message through the agent and render both sides of it."""
    st.session_state.display_messages.append(("user", user_text))
    with st.chat_message("user"):
        st.write(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply = agent.send_user_message(user_text)
        st.write(reply)
    st.session_state.display_messages.append(("assistant", reply))


uploaded = st.file_uploader(
    "Attach a photo ID if the agent asks for one", type=["jpg", "jpeg", "png"]
)

# The mock verifier keys off the filename (see mock_api.py), so uploading
# a file sends its name to the agent as a normal chat turn — no real image
# data needs to reach Claude for this project.
if uploaded is not None and uploaded.name != st.session_state.processed_upload:
    st.session_state.processed_upload = uploaded.name
    _send_turn(f"[Uploaded ID photo: {uploaded.name}]")
    st.rerun()

user_text = st.chat_input("Message Partiful support...")
if user_text:
    _send_turn(user_text)
    st.rerun()
