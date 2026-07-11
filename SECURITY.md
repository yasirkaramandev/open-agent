# Security

OpenAgent runs AI backends that can read, edit, and execute code on your machine. These are the
guardrails it enforces, and how to report issues.

## Credentials

- API keys are stored in the **OS keychain** by default (via `keyring`). Alternatives: reference an
  environment variable (`--key-env`), a session-only secret, or an external command.
- Keys are **never** written to the SQLite DB, `events.jsonl`, `logs.txt`, `OPENAGENT.md`, or passed
  as command-line arguments.
- For CLI subprocesses, a run's credential is injected **only into the child process environment**;
  the parent process environment is not used to carry provider keys.

## Secret redaction

Every string written to logs, events, and reports passes through a redactor that masks common secret
shapes (`sk-…`, `Bearer …`, `Authorization: …`, `*_API_KEY=…`, GitHub tokens). Model-produced summary
text is redacted before it is written to `output.md` / `result.json`.

## Workspace isolation

- File-changing runs execute in an **isolated git worktree** on a fresh `openagent/run_<id>` branch.
  Your working tree is untouched until you choose to apply/merge.
- Non-git projects fall back to a temporary copy, flagged as **lower safety** in the UI.
- All tool file paths are validated to stay inside the workspace (path-traversal / symlink escapes
  are rejected).

## Command policy

Before any shell command runs it is screened. **Denied** categorically: `git push`, `npm publish`,
`pip/twine upload`, `docker login`, cloud CLI logins, `sudo`, reads of `.env` / SSH keys /
credentials, and direct keychain access. **Requires approval**: `rm -rf`, `git reset --hard`,
`git clean`, disk-level operations, and (when the profile disallows network) installs/downloads.

## Process management

CLI subprocesses run with a minimal environment. Cancelling a run terminates the **entire process
tree** (graceful `SIGTERM` → force `SIGKILL`). If OpenAgent exits unexpectedly, orphaned runs are
detected and marked on the next launch.

## Reasoning privacy

Raw provider chain-of-thought is treated as sensitive metadata and is **not** surfaced verbatim to
the user or written to artifacts.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository, or contact the maintainer directly
rather than filing a public issue. Include reproduction steps and the affected version.
