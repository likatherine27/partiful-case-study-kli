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

import sys
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
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


def _letter_avatar(letter: str, bg: str, fg: str, size: int = 96) -> Image.Image:
    """Renders a small square image with one bold centered letter.

    st.chat_message's avatar= only accepts None, "user"/"assistant", a
    real emoji, or an actual image — a plain string like "P" gets
    treated as a file path and throws (confirmed the hard way). A
    generated image sidesteps that entirely and bakes the exact colors
    in directly, no CSS targeting of Streamlit's internal markup needed.
    """
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf", int(size * 0.5)
        )
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]),
        letter,
        font=font,
        fill=fg,
    )
    return img


# Same style as the user avatar: light grey background, darker grey mark.
ASSISTANT_AVATAR = _letter_avatar("P", bg="#D7D6DC", fg="#55535E")

_STYLE = """
<style>
:root {
    --pf-text: #F5F3F8;
    --pf-overlay: rgba(255,255,255,0.08);
    --pf-overlay-border: rgba(255,255,255,0.14);
    --pf-overlay-assistant: rgba(124,141,196,0.16);
    --pf-overlay-assistant-border: rgba(124,141,196,0.28);
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
[data-testid="stChatInput"]:focus-within {
    border-color: #FFFFFF !important;
}
[data-testid="stChatInput"]:focus-within > div {
    border-color: #FFFFFF !important;
}
[data-testid="stChatMessage"] {
    background: transparent !important;
    /* Center the avatar on the bubble's vertical middle rather than its
       top edge — the bubble's own padding is taller than the avatar, so
       top-alignment left single-line text looking bottom-heavy next to
       the avatar. */
    align-items: center !important;
    gap: 10px !important;
}
[data-testid="stChatMessageContent"] p {
    margin: 0;
    font-size: 15px;
    line-height: 1.5;
}
/* Streamlit gives stMarkdownContainer a -16px bottom margin to cancel
   out the browser's default <p> spacing in normal document flow. Inside
   this flex-centered row that collapses the block's LAYOUT height down
   near zero while the real text still paints at full height with
   overflow:visible — so the bubble's padding ends up wrapping an
   assumed-empty box and the text visually hangs off the bottom instead
   of sitting centered in it. Neutralizing it lets padding wrap the
   text's true height. */
[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"] {
    margin-bottom: 0 !important;
}
/* User row: icon on the right */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse;
    justify-content: flex-end;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    background: var(--pf-overlay);
    border: 1px solid var(--pf-overlay-border);
    border-radius: 16px;
    max-width: 68%;
    /* Padding (not a fixed/min height) so the bubble is naturally
       centered around single-line text AND grows with multi-line text
       instead of clipping it — a fixed height fights wrapped content. */
    padding: 19px 18px;
    color: var(--pf-text);
    /* Streamlit auto-centers a max-width content block by default,
       which was splitting the leftover space into two large margins
       instead of letting the bubble sit snug against the avatar. Pin
       it to the avatar side (right) so only `gap` separates them. */
    margin-left: auto !important;
    margin-right: 0 !important;
}
/* Assistant row. A custom avatar image (see ASSISTANT_AVATAR) renders as
   a bare <img>, with NO data-testid at all — Streamlit only adds
   stChatMessageAvatarAssistant for its own built-in icon — so it's
   targeted structurally below by "the first child that isn't the user
   avatar" instead (any tag, not just div, since it's an <img>). */
[data-testid="stChatMessage"]:has(> :first-child:not([data-testid="stChatMessageAvatarUser"])) [data-testid="stChatMessageContent"] {
    background: var(--pf-overlay-assistant);
    border: 1px solid var(--pf-overlay-assistant-border);
    border-radius: 16px;
    max-width: 68%;
    padding: 19px 18px;
    color: var(--pf-text);
    margin-left: 0 !important;
    margin-right: auto !important;
}
[data-testid="stChatMessageAvatarUser"] {
    background: #D7D6DC !important;
    color: #55535E !important;
}
[data-testid="stChatMessage"] > div:first-child:not([data-testid="stChatMessageAvatarUser"]) {
    background: #D7D6DC !important;
    color: #55535E !important;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
}
[data-testid="stChatInputSubmitButton"]:not(:disabled) {
    background-color: #D7D6DC !important;
}
[data-testid="stChatInputSubmitButton"]:not(:disabled) svg {
    fill: #55535E !important;
}
</style>
"""

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
    avatar = ASSISTANT_AVATAR if role == "assistant" else None
    with st.chat_message(role, avatar=avatar):
        st.write(text)


def _send_turn(user_text: str) -> None:
    """Send one message through the agent and render both sides of it."""
    st.session_state.display_messages.append(("user", user_text))
    with st.chat_message("user"):
        st.write(user_text)

    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
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
