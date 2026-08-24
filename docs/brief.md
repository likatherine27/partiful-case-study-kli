# Background: Change Phone Number

Within Partiful, you can change your phone number self-serve. However, it
requires that you have access to your previous number, which isn't always
the case.

When a user hits this issue, they reach out via hello@partiful.com and it
gets assigned to our support team. Currently, this is a highly manual
process:

1. The user reaches out requesting a phone number change.
2. This gets assigned to someone from our support team, who first asks if
   they have access to their old phone.
3. If the user says they have access to their old phone, they are
   redirected to change their phone number self-service via logging in
   (see instructions
   [here](https://help.partiful.com/hc/en-us/articles/26025082969243-Can-I-change-my-phone-number)).
4. If the user says they have lost access to their old phone, we request
   that they submit ID verification to confirm their identity.
5. If we are able to verify the ID, we will proceed with the phone number
   change.

This agent automates that flow end to end, escalating to a human only
when the automated path genuinely can't resolve it. See the main
[README](../README.md) for how it works, and the
[scoping doc](https://docs.google.com/document/d/1IyH35stH8aZunloDUODHVpDqJWdmLKg4IevVmgf7ssI/edit?tab=t.0#heading=h.3f1c4oblsxqg)
for full scoping rationale and what's deliberately out of scope for this
version.
