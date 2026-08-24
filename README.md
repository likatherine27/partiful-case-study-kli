# Partiful Support Agent — Change Phone Number

An AI agent that automates Partiful's "I lost access to my old phone number"
support flow: it identifies the account, collects and verifies a government
ID, and (only after a real pass) commits the phone number change — all with
as little human involvement as possible.

Background on the manual process this replaces is in
[docs/brief.md](docs/brief.md). Full scoping rationale, and what's
deliberately out of scope for this version, is in the **[scoping doc](https://docs.google.com/document/d/1IyH35stH8aZunloDUODHVpDqJWdmLKg4IevVmgf7ssI/edit?tab=t.i96r97potq5x#heading=h.jv5pwdiiid4y)**.

## How it works

The support flow is a strict decision tree (do they have their old phone? →
look up the account → verify ID → change the number), so the agent is a
single Claude conversation with a small set of tools, not a multi-agent
system:

1. The user chats with the agent about their locked-out account.
2. Claude decides which tool to call next (look up the account, verify an
   uploaded ID, commit the change, escalate to a human, etc.) based on the
   system prompt's flow.
3. Every consequential action is validated against `SessionState`'s
   guardrails **in plain Python** before it's allowed to run — so no amount
   of clever prompting can talk the agent into changing a number without a
   passed ID check. This is deliberate: the model drives the conversation,
   but it does not get to decide what's allowed to happen.
4. Real internal-API calls (account lookup, ID verification, committing the
   change, locking an account) have no backend to call from this
   environment, so they're stubbed in `mock_api.py`. Every call is printed
   to the terminal as `[API CALL] ...` and logged to `state.actions_taken`,
   which the test suite asserts against to verify the right sequence of
   actions ran.

```
app.py                        Streamlit chat UI (rendering only, no business logic)
src/partiful_agent/
  agent.py                    Conversation loop: talks to Claude, dispatches tool calls
  prompts.py                  System prompt — the flow, tone, and rules Claude follows
  tools.py                    Tool schemas + implementations Claude can call
  state.py                    SessionState + the guardrails that make the agent trustworthy
  mock_api.py                 Stand-in for Partiful's internal APIs (prints every call)
  config.py                   Tunable constants (retry limits, timeouts, model, pricing)
tests/
  test_cases.yaml             The test set (20 scenarios, happy path + adversarial)
  run_test_set.py             Runs test_cases.yaml as real conversations against the live API
  test_guardrails.py          Fast, free unit tests for the security rules (no network calls)
  test_inactivity.py          Unit tests for the "are you still there?" / timeout logic
assets/                       Sample ID images used by the test set (see generate_sample_ids.py)
docs/brief.md                 Background on the manual process this agent replaces
```

### Guardrails (what keeps this safe to automate)

All of the following are enforced in `state.py`, independent of anything the
model says:

- A phone number can only be changed after ID verification **passes** for
  an **identified** account. There is no code path around this.
- Three failed ID attempts locks the account from further automated changes.
- Three unclear responses, three bad account lookups, or three invalid
  proposed numbers each end the session and point the user to
  `hello@partiful.com` instead of looping forever.
- A proposed new number that's already attached to a *different* account,
  or a request that isn't a phone-number change at all, escalates
  immediately rather than being treated as a retryable typo.
- A quiet user gets a check-in after 15 minutes and the session closes
  after 5 more minutes of silence.

## Running the agent

Requires Python 3.11+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then paste your ANTHROPIC_API_KEY into .env
streamlit run app.py
```

This opens the chat UI at `http://localhost:8501`. To exercise the ID
verification step, upload one of the fixtures in `assets/` when prompted
(`valid_id.jpg` passes; `blurry_id.jpg`, `expired_id.jpg`, and
`mismatch_id.jpg` each fail for a different reason — the mock verifier keys
off the filename, not the pixels, so a real image is never sent to Claude).
Every mocked internal-API call the agent makes is printed to the terminal
running `streamlit`, since a real end user would never see that panel.

## Testing

Two layers, matching what's fast/free versus what proves the real thing:

```bash
# Fast, free, deterministic — the guardrails and inactivity logic, no network calls
pytest tests/ -v

# The test set — 20 real conversations against the live Claude API, checked
# against the agent's own ground truth (state.outcome, exact tool calls
# made), not fuzzy text matching. Prints real dollar cost at the end.
python3 tests/run_test_set.py

# Re-run just the case(s) you're debugging instead of paying for all 20
python3 tests/run_test_set.py happy_path_verified_and_changed
```

`tests/test_cases.yaml` covers the happy paths (self-serve redirect,
verify-and-change, three-strikes lockout), every exhaustion path (unclear
intent, bad phone lookups, bad new numbers), a couple of regression cases
for real bugs hit during development, and an adversarial case that tries
to talk the agent into skipping verification outright.

## Assumptions & scope

Notable assumptions made to keep this a buildable MVP (full rationale in
the scoping doc):

- Phone numbers are validated for any region (via `phonenumbers`/libphonenumber),
  not just US (`+1`) — but the mock account directory itself only seeds US
  numbers, so a non-US lookup will format-validate and then correctly find
  no account.
- ID verification is a deterministic stub keyed off the uploaded file's
  name, standing in for a real vendor (e.g. Persona, Stripe Identity).
- Internal API calls are printed, not executed — this repo has no access
  to Partiful's real backend services.

What's explicitly **out of scope for MVP** — and why — is written up in the
scoping doc linked above, not duplicated here.
