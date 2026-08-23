"""Streamlit chat UI for the Partiful phone-number-change agent.

This file only renders. It holds no business logic of its own — every
decision (what to say, what tool to call, whether an action is allowed)
happens inside agent.py / tools.py / state.py. That split is what lets
tests/run_test_set.py drive the exact same Agent class with no UI at all,
so the demo and the automated tests exercise identical code.

This view intentionally shows only what a real user would see — no
internal session/debug panel. The internal-API action log the assignment
asks for still happens (see mock_api.py's print calls); it just surfaces
in the terminal running `streamlit run`, not on screen, since a real user
would never see that either.
"""

import sys
from pathlib import Path

import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, str(Path(__file__).parent / "src"))

from partiful_agent.agent import Agent  # noqa: E402
from partiful_agent.state import SessionOutcome  # noqa: E402

st.set_page_config(page_title="Partiful Support", page_icon="📱")

# Streamlit only re-runs this script in response to user interaction, but
# an inactivity check has to fire even when the user does nothing at all.
# This forces a re-run every few seconds so check_inactivity() below gets a
# chance to notice a quiet user without anyone touching the page.
st_autorefresh(interval=15_000, key="inactivity_poll")

st.markdown(
    """
    <style>
    .typing-indicator { display: flex; gap: 4px; padding: 4px 0 2px; }
    .typing-indicator span {
        width: 7px; height: 7px; border-radius: 50%;
        background: #9AA1AC;
        animation: typing-bounce 1.1s infinite ease-in-out;
    }
    .typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
    .typing-indicator span:nth-child(3) { animation-delay: 0.30s; }
    @keyframes typing-bounce {
        0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
        30% { transform: translateY(-5px); opacity: 1; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
_TYPING_INDICATOR = (
    '<div class="typing-indicator"><span></span><span></span><span></span></div>'
)


def new_agent() -> Agent:
    return Agent()


if "agent" not in st.session_state:
    st.session_state.agent = new_agent()
    st.session_state.display_messages = []  # [(role, text), ...]
    st.session_state.processed_upload = None

agent: Agent = st.session_state.agent


def _awaiting_id_upload() -> bool:
    """True exactly when an ID upload is a meaningful next step.

    Reuses the same facts state.py's guardrails are built on (account
    identified, not yet verified, not locked, session still open) rather
    than guessing from the chatbot's wording — so the upload button shows
    up precisely during the window where verify_id would actually run.
    """
    state = agent.state
    return (
        state.account is not None
        and not state.id_verified
        and not state.is_locked
        and state.outcome == SessionOutcome.IN_PROGRESS
    )


st.title("Partiful Support")

# Runs on every single script execution, including autorefresh-triggered
# ones with no user action at all — that's what lets "are you still
# there?" and the eventual timeout fire on their own.
inactivity_message = agent.check_inactivity()
if inactivity_message is not None:
    st.session_state.display_messages.append(("assistant", inactivity_message))

for role, text in st.session_state.display_messages:
    with st.chat_message(role):
        st.write(text)


def _send_turn(user_text: str) -> None:
    """Send one message through the agent and render both sides of it."""
    st.session_state.display_messages.append(("user", user_text))
    with st.chat_message("user"):
        st.write(user_text)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown(_TYPING_INDICATOR, unsafe_allow_html=True)
        reply = agent.send_user_message(user_text)
        # Persist to session_state BEFORE the next Streamlit call. An
        # autorefresh-triggered rerun (see check_inactivity above) can
        # interrupt script execution at the next checkpoint — if the
        # append happened after placeholder.write() instead, an
        # unlucky-timed interrupt could drop this turn from the visible
        # history even though the agent's own memory still has it.
        st.session_state.display_messages.append(("assistant", reply))
        placeholder.write(reply)


if agent.state.outcome == SessionOutcome.TIMED_OUT:
    # A timeout is the one terminal state that really ends things — every
    # other terminal outcome leaves the chat open for "anything else?" or
    # a redirect, but there's no one left to talk to here.
    if st.button("Start a new chat"):
        st.session_state.agent = new_agent()
        st.session_state.display_messages = []
        st.session_state.processed_upload = None
        st.rerun()
else:
    if _awaiting_id_upload():
        uploaded = st.file_uploader(
            "Attach a photo ID", type=["jpg", "jpeg", "png"]
        )
        # The mock verifier keys off the filename (see mock_api.py), so
        # uploading a file sends its name to the agent as a normal chat
        # turn — no real image data needs to reach Claude for this project.
        if uploaded is not None and uploaded.name != st.session_state.processed_upload:
            st.session_state.processed_upload = uploaded.name
            _send_turn(f"[Uploaded ID photo: {uploaded.name}]")
            st.rerun()

    user_text = st.chat_input("Message Partiful support...")
    if user_text:
        _send_turn(user_text)
        st.rerun()
