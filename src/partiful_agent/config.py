"""Tunable constants for the phone-number-change agent.

Everything a reviewer might want to change lives here rather than being
scattered through the code. In Java terms, this is the `static final`
block for the whole application.
"""

# --- Model -----------------------------------------------------------------

MODEL = "claude-sonnet-5"

# Cap on how long a single agent reply can be. Support replies are short;
# this also stops a runaway response from burning tokens.
MAX_TOKENS = 1024

# Safety cap on tool calls within a single user turn. Claude is expected to
# call one or two tools and then reply with text; this just guards against
# the model looping on tool calls indefinitely and never responding.
MAX_TOOL_ITERATIONS = 8


# --- Policy: ID verification ----------------------------------------------

# A user gets three total attempts to pass ID verification. On the third
# failure the account is locked from further automated changes.
MAX_ID_ATTEMPTS = 3


# --- Policy: session inactivity -------------------------------------------

# If the user goes quiet this long, the agent checks whether they're still there.
INACTIVITY_PROMPT_SECONDS = 15 * 60  # 15 minutes

# After that check-in, this is how long they have to respond before the
# session is closed out and they're told to start a fresh chat.
INACTIVITY_TIMEOUT_SECONDS = 5 * 60  # 5 minutes


# --- Customer-facing references -------------------------------------------

SELF_SERVE_HELP_URL = (
    "https://help.partiful.com/hc/en-us/articles/"
    "26025082969243-Can-I-change-my-phone-number"
)

SUPPORT_EMAIL = "hello@partiful.com"
