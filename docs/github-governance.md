# GitHub governance setup

These settings cannot be committed to the repository — they live in GitHub's own configuration.
Run them once, from a machine authenticated as the repository owner (`gh auth status` should show
`yasirkaramandev`).

Everything here is reversible except where noted. Read the ruleset section before running it: it
locks direct pushes to `main` for **you as well**, which is the point.

---

## 1. Merge strategy

Squash is the only strategy left enabled, so one pull request becomes exactly one commit on
`main`. This is what keeps `git log main` a readable list of changes rather than a transcript of
how each change was developed.

```bash
gh api -X PATCH repos/yasirkaramandev/openagent \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true \
  -F allow_auto_merge=true
```

---

## 2. Branch protection for `main`

A ruleset rather than the legacy branch-protection API — rulesets are what GitHub develops
against now, and they express "no bypass" cleanly.

**Before you run this:** after it lands you can no longer `git push` to `main`. Every change goes
through a pull request whose checks pass. If you are mid-flight on something uncommitted, land it
first.

```bash
cat > /tmp/openagent-main-ruleset.json <<'JSON'
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "test (ubuntu, py3.10)" },
          { "context": "test (ubuntu, py3.11)" },
          { "context": "test (ubuntu, py3.12)" },
          { "context": "smoke (macos-latest)" },
          { "context": "smoke (windows-latest)" },
          { "context": "codeql (python)" },
          { "context": "codeql (actions)" },
          { "context": "container-sandbox (real Docker)" }
        ]
      }
    }
  ]
}
JSON

gh api -X POST repos/yasirkaramandev/openagent/rulesets \
  --input /tmp/openagent-main-ruleset.json
```

### On `required_approving_review_count: 0`

You are the only maintainer. Requiring an approving review from someone else would make the
repository unmergeable, and requiring one from yourself is theatre GitHub does not support
anyway. What is actually enforced here is the part that catches real mistakes: a pull request must
exist, CI must pass, the branch must be current with `main`, and every review thread must be
resolved. Add a review requirement the day a second maintainer joins.

### Check names must match exactly

The `context` strings above are job **names** as GitHub reports them, which for a matrix job means
the interpolated name (`test (ubuntu, py3.10)`), not the job id (`test`). If a required check name
does not match any job, pull requests block forever waiting for a check that will never report.

Verify against a real run before trusting the list:

```bash
gh pr checks <PR-NUMBER>          # names as reported, on an open PR
```

Note that the installer and wheel-lifecycle jobs are deliberately **not** required: they are slow
and their matrix names shift. Promote them once their names are stable.

---

## 3. Labels

```bash
repo=yasirkaramandev/openagent

# Priority — what stops a release. See docs/release-decision-matrix in the plan.
gh label create "priority:P0" -R $repo -c B60205 -d "Secret leak, data loss, DB corruption — all work stops" --force
gh label create "priority:P1" -R $repo -c D93F0B -d "Blocks the current release, fixed in this milestone" --force
gh label create "priority:P2" -R $repo -c FBCA04 -d "Triaged before RC; may move to the next patch" --force
gh label create "priority:P3" -R $repo -c FEF2C0 -d "Backlog" --force

# Type
gh label create "type:bug"       -R $repo -c D73A4A --force
gh label create "type:security"  -R $repo -c B60205 --force
gh label create "type:refactor"  -R $repo -c C5DEF5 --force
gh label create "type:test"      -R $repo -c BFDADC --force
gh label create "type:docs"      -R $repo -c 0075CA --force
gh label create "type:chore"     -R $repo -c EEEEEE --force
gh label create "type:migration" -R $repo -c 5319E7 --force
gh label create "type:feature"   -R $repo -c A2EEEF --force

# Area — mirrors the source tree so triage does not need a judgement call.
for area in auth credentials cli updater git database provider agent \
            generated-files tui installer container dependencies ci; do
  gh label create "area:$area" -R $repo -c 1D76DB --force
done

# Status
gh label create "status:needs-repro"  -R $repo -c E4E669 --force
gh label create "status:ready"        -R $repo -c 0E8A16 --force
gh label create "status:in-progress"  -R $repo -c 1D76DB --force
gh label create "status:blocked"      -R $repo -c B60205 --force
gh label create "status:needs-review" -R $repo -c FBCA04 --force

# Release
gh label create "release:0.1.5" -R $repo -c 0E8A16 --force
gh label create "release:0.1.6" -R $repo -c 0E8A16 --force
gh label create "release:future" -R $repo -c EEEEEE -d "After the feature freeze lifts" --force
```

---

## 4. Milestones

```bash
repo=yasirkaramandev/openagent

gh api -X POST repos/$repo/milestones \
  -f title="0.1.5" \
  -f state="open" \
  -f description="Authentication, Git isolation, updater correctness. No schema changes."

gh api -X POST repos/$repo/milestones \
  -f title="0.1.6" \
  -f state="open" \
  -f description="Provider/agent concurrency, DB integrity, generated-file locking. Migration 0012."
```

---

## 5. Verification

```bash
repo=yasirkaramandev/openagent

gh api repos/$repo/rulesets --jq '.[] | "\(.name): \(.enforcement)"'
gh api repos/$repo --jq '{squash: .allow_squash_merge, merge: .allow_merge_commit, rebase: .allow_rebase_merge}'
gh label list -R $repo --limit 60
gh api repos/$repo/milestones --jq '.[].title'
```

Then confirm the gate actually holds — this should be **rejected**:

```bash
git checkout main && git commit --allow-empty -m "governance smoke" && git push
```

If that push succeeds, the ruleset is not active or you are bypassing it; check `bypass_actors` is
empty and `enforcement` is `active`.

---

## 6. Rolling back

```bash
gh api repos/yasirkaramandev/openagent/rulesets --jq '.[] | select(.name=="main-protection") | .id'
gh api -X DELETE repos/yasirkaramandev/openagent/rulesets/<ID>
```

Labels and milestones are additive and safe to leave in place.
