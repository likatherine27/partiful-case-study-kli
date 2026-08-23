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

Visual styling is meant to feel like it belongs on Partiful's own site:
dark theme, a blurred multicolor gradient wash, and a rounded, playful
display font, matching the product's actual look. The badge/wordmark
in the header is an original rendering (gradient badge + monogram), not
a reproduction of Partiful's registered logo mark.
"""

import sys
from pathlib import Path

import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, str(Path(__file__).parent / "src"))

from partiful_agent.agent import Agent  # noqa: E402
from partiful_agent.state import SessionOutcome  # noqa: E402

def _html(markup: str) -> str:
    """Prepares raw HTML/CSS for st.markdown(..., unsafe_allow_html=True).

    Two independent markdown quirks otherwise corrupt this: a line
    indented 4+ spaces is treated as a preformatted code block (real CSS
    is naturally nested, so Python's source indentation trips this), and
    — the one that actually bit us — a BLANK line terminates a raw-HTML
    block outright, even in the middle of a still-open <style> tag,
    silently dumping everything after it into a visible <p> instead.
    Flattening indentation and dropping blank lines avoids both; CSS/HTML
    don't care about whitespace anyway.
    """
    return "\n".join(
        line.strip() for line in markup.strip().splitlines() if line.strip()
    )


st.set_page_config(page_title="Partiful Support", page_icon="📱")

# Streamlit only re-runs this script in response to user interaction, but
# an inactivity check has to fire even when the user does nothing at all.
# This forces a re-run every few seconds so check_inactivity() below gets a
# chance to notice a quiet user without anyone touching the page.
st_autorefresh(interval=60_000, key="inactivity_poll")

st.markdown(
    _html(
        """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
    :root {
        --pf-bg: #0B0910;
        --pf-surface: #18141F;
        --pf-surface-2: #201B29;
        --pf-border: rgba(255,255,255,0.08);
        --pf-text: #F3EFF7;
        --pf-text-muted: #9992A6;
        --pf-pink: #FF6FA8;
        --pf-purple: #A66BFF;
        --pf-orange: #FFB073;
        --pf-yellow: #FDE38A;
        --pf-user-bubble: linear-gradient(135deg, #FF6FA8 0%, #B072FF 100%);
    }

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    }

    /* Blurred hero gradient wash behind the header, matching the
       colorful blurred backgrounds on Partiful's own pages. */
    .pf-hero-wash {
        position: fixed;
        top: -220px;
        left: -120px;
        width: 900px;
        height: 620px;
        z-index: -1;
        background:
            radial-gradient(circle at 15% 25%, var(--pf-pink) 0%, transparent 45%),
            radial-gradient(circle at 55% 10%, var(--pf-purple) 0%, transparent 50%),
            radial-gradient(circle at 80% 35%, var(--pf-orange) 0%, transparent 45%),
            radial-gradient(circle at 40% 50%, var(--pf-yellow) 0%, transparent 40%);
        filter: blur(90px);
        opacity: 0.35;
        pointer-events: none;
    }

    .pf-header-row {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 28px;
    }
    .pf-badge {
        width: 34px;
        height: 34px;
        border-radius: 10px;
        background: linear-gradient(135deg, var(--pf-pink), var(--pf-purple));
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Fredoka', sans-serif;
        font-weight: 700;
        font-size: 19px;
        color: white;
        flex: none;
    }
    .pf-wordmark {
        font-family: 'Fredoka', sans-serif;
        font-weight: 600;
        font-size: 19px;
        color: var(--pf-text);
        letter-spacing: -0.01em;
    }
    .pf-tag {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 12px;
        font-weight: 600;
        color: var(--pf-text-muted);
        background: var(--pf-surface-2);
        border: 1px solid var(--pf-border);
        padding: 3px 10px;
        border-radius: 999px;
        margin-left: 2px;
    }

    h1 {
        font-family: 'Fredoka', sans-serif !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }

    @media (prefers-reduced-motion: reduce) {
        .typing-indicator span { animation: none !important; }
    }

    .typing-indicator { display: flex; gap: 4px; padding: 4px 0 2px; }
    .typing-indicator span {
        width: 7px; height: 7px; border-radius: 50%;
        background: var(--pf-pink);
        animation: typing-bounce 1.1s infinite ease-in-out;
    }
    .typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
    .typing-indicator span:nth-child(3) { animation-delay: 0.30s; }
    @keyframes typing-bounce {
        0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
        30% { transform: translateY(-5px); opacity: 1; }
    }

    /* Chat bubbles: hide Streamlit's default avatar icons and turn each
       message row into a properly aligned, rounded chat bubble instead. */
    [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessageAvatarAssistant"] {
        display: none !important;
    }
    [data-testid="stChatMessage"] {
        display: flex !important;
        background: transparent !important;
        margin-bottom: 6px;
    }
    [data-testid="stChatMessageContent"] {
        border-radius: 18px;
        padding: 10px 16px;
        max-width: 78%;
        width: fit-content;
        flex-grow: 0 !important;
    }
    [data-testid="stChatMessageContent"] p {
        margin: 0;
        font-size: 15px;
        line-height: 1.5;
    }
    /* Assistant: left-aligned, dark card */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        justify-content: flex-start;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
        background: var(--pf-surface);
        border: 1px solid var(--pf-border);
        color: var(--pf-text);
    }
    /* User: right-aligned, gradient bubble */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        justify-content: flex-end;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background: var(--pf-user-bubble);
        color: white;
    }

    /* Chat input: rounded pill, matching the search-bar style on
       Partiful's own help center. */
    [data-testid="stChatInput"] {
        border-radius: 999px !important;
        border: 1px solid var(--pf-border) !important;
        background: var(--pf-surface) !important;
    }
    [data-testid="stChatInput"] textarea {
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }

    /* Buttons: solid rounded pill, matching "+Create" on their homepage */
    [data-testid="stButton"] button {
        border-radius: 999px !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 600 !important;
        background: var(--pf-text) !important;
        color: #16121C !important;
        border: none !important;
    }

    /* File uploader: dark rounded card with a gradient-tinted border */
    [data-testid="stFileUploaderDropzone"] {
        background: var(--pf-surface) !important;
        border-radius: 16px !important;
        border: 1px dashed var(--pf-purple) !important;
    }
    </style>
    <div class="pf-hero-wash"></div>
    """
    ),
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


st.markdown(
    _html(
        """
    <div class="pf-header-row">
        <div class="pf-badge">p</div>
        <div class="pf-wordmark">partiful</div>
        <div class="pf-tag">Support</div>
    </div>
    """
    ),
    unsafe_allow_html=True,
)
st.title("Support")

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
