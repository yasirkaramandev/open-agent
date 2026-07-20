<!--
Squash-merge is the only enabled strategy, so this description becomes the commit message on
`main`. Write it for someone reading `git log` in a year, not for the reviewer reading it today.
-->

## What changed

<!-- One paragraph. What the code does now that it did not do before. -->

## Why

<!--
The root cause, not the symptom. "Fixes the crash" is not a root cause; "the tailer replayed the
initial event list into a second list that was never released" is.

Closes #
-->

## Definition of Done

A fix is not done because the code is written. Tick what genuinely applies; strike out what does
not apply and say why.

- [ ] Root cause written down (above, not just in the linked issue)
- [ ] A regression test was added that **fails without this change** — and I ran it against the
      unpatched code to confirm it fails
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Subprocess tests pass (if this touches child environments, git, or the CLI adapters)
- [ ] Migration tests pass (if this touches the schema)
- [ ] Doctor surfaces the new state (if this adds a failure mode a user can hit)
- [ ] User-facing errors are actionable — they say what to do, not only what went wrong
- [ ] Secret redaction verified (if this touches credentials, subprocess env, logs, or artifacts)
- [ ] Documentation updated (README / SECURITY.md / CHANGELOG.md)

## Verification

<!--
The exact commands you ran, and their result. Not "tests pass" — the invocation and the count.

    pytest tests/security -m security -k git_hook
    12 passed in 3.4s
-->

## Risk

<!--
What could this break that CI would not catch? Schema changes, concurrency, credential handling
and subprocess environments all deserve an explicit sentence here. "None" is a valid answer for a
docs change and a suspicious one for anything else.
-->
