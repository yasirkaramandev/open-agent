# Incident response

On suspected token exposure: disable write feature flags, rotate the envelope key version, revoke the
affected Google grants, invalidate application sessions, freeze proposal execution, preserve
redacted audit evidence, and reconcile unknown remote outcomes. Do not replay a timed-out write.

On webhook abuse: rotate the verification secret, reject timestamps outside the replay window,
disable the subscription, drain the dead-letter queue into quarantine, and reconcile through bounded
official API polling with ETags.

Restore exercises must verify the PostgreSQL backup, audit hash-chain continuity, credential
ciphertext readability by an approved key version, and absence of pending EXECUTING proposals before
traffic resumes.
