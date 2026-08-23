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

Styling here follows Katherine's explicit direction: a fixed gradient
background, translucent overlay bubbles for the user, plain unbubbled text
for the assistant, and a best-effort (not a pixel trace) approximation of
Partiful's logo mark on the assistant's avatar.
"""

import base64
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
st_autorefresh(interval=60_000, key="inactivity_poll")


def _html(markup: str) -> str:
    """Prepares raw HTML/CSS for st.markdown(..., unsafe_allow_html=True).

    Two markdown quirks otherwise corrupt this: a line indented 4+ spaces
    is treated as a preformatted code block (real CSS is naturally
    nested, so Python's source indentation trips this), and a BLANK line
    terminates a raw-HTML block outright, even mid-<style>-tag, silently
    dumping everything after it into a visible <p>. Flattening
    indentation and dropping blank lines avoids both.
    """
    return "\n".join(
        line.strip() for line in markup.strip().splitlines() if line.strip()
    )


# A best-effort, original approximation of Partiful's logo mark (an
# abstract flowing loop) for the assistant's avatar — not a trace of
# their actual registered artwork, just an attempt at the same spirit.
_SWIRL_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<path d="M62 78 C40 82, 22 68, 24 48 C26 26, 50 14, 68 24
         C84 33, 84 54, 68 60 C56 65, 44 58, 46 46"
      fill="none" stroke="url(#g)" stroke-width="13" stroke-linecap="round"/>
<defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="#F5F1FA"/>
<stop offset="100%" stop-color="#C9B8E8"/>
</linearGradient>
</defs>
</svg>
"""
_SWIRL_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    _SWIRL_SVG.encode()
).decode()

_STYLE = """
<style>
:root {
    --pf-text: #F5F3F8;
    --pf-overlay: rgba(255,255,255,0.08);
    --pf-overlay-border: rgba(255,255,255,0.14);
}
[data-testid="stApp"] {
    background:
        radial-gradient(ellipse 900px 650px at 8% 0%, #8D6B82 0%, transparent 55%),
        radial-gradient(ellipse 900px 650px at 92% 0%, #7C8DC4 0%, transparent 55%),
        linear-gradient(180deg, #5C4E6E 0%, #2E2738 38%, #100D16 80%);
    background-attachment: fixed;
}
h1 {
    color: var(--pf-text) !important;
}
.pf-subheader {
    font-size: 13px;
    color: rgba(245,243,248,0.6);
    margin-top: -14px;
    margin-bottom: 22px;
}
.typing-indicator { display: flex; gap: 4px; padding: 4px 0 2px; }
.typing-indicator span {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--pf-text);
    opacity: 0.6;
    animation: typing-bounce 1.1s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.30s; }
@keyframes typing-bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
    30% { transform: translateY(-5px); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
    .typing-indicator span { animation: none !important; }
}
[data-testid="stChatInput"] {
    background: var(--pf-overlay) !important;
    border: 1px solid var(--pf-overlay-border) !important;
    border-radius: 16px !important;
}
[data-testid="stChatMessage"] {
    background: transparent !important;
}
[data-testid="stChatMessageContent"] p {
    margin: 0;
    font-size: 15px;
    line-height: 1.5;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    background: var(--pf-overlay);
    border: 1px solid var(--pf-overlay-border);
    border-radius: 16px;
    padding: 10px 14px;
    color: var(--pf-text);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
    background: transparent;
    border: none;
    padding: 6px 0;
    color: var(--pf-text);
}
[data-testid="stChatMessageAvatarUser"] {
    background: #D7D6DC !important;
    color: #55535E !important;
}
[data-testid="stChatMessageAvatarAssistant"] {
    background: #17141D !important;
    border-radius: 9px !important;
    background-image: url('__SWIRL_URI__') !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: 62% !important;
}
[data-testid="stChatMessageAvatarAssistant"] [data-testid="stIconMaterial"] {
    display: none !important;
}
</style>
""".replace("__SWIRL_URI__", _SWIRL_DATA_URI)

st.markdown(_html(_STYLE), unsafe_allow_html=True)

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
st.markdown(
    _html('<p class="pf-subheader">what can we help you with?</p>'),
    unsafe_allow_html=True,
)

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
        # Persist to session_state BEFORE the next Streamlit call — see
        # the note in memory/commit history about why ordering here
        # matters for a rerun that lands mid-turn.
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
