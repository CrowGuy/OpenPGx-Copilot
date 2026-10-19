---
name: start-issue
description: Start work on a GitHub issue. Claims it, then moves the session into the issue's own worktree and test database. Use before implementing any issue.
---

# Start an issue

Several sessions implement issues at once. Each issue gets its own worktree, branch and test database, so no two sessions share a checkout or reset each other's data. The main checkout belongs to no session.

Argument: the issue number `N`.

Write every command literally, one command per call. Inside a worktree the harness refuses `sh <script>`, commands named by a variable, and anything aimed at the main checkout.

## Prerequisites

Tools come from two conda envs, reached by name with `conda run -n`, so the commands are the same on every machine:

- `gwas-env`: Python with `psycopg`
- `pg-client`: `psql` 18, kept out of `gwas-env` (`conda create -n pg-client -c conda-forge postgresql=18`)

The local PostgreSQL from `db/compose.yaml` is running at `127.0.0.1:5432`.

## 1. Check the issue is free

```bash
gh issue view N --json state,assignees,labels,title
gh api repos/CrowGuy/OpenPGx-Copilot/issues/N --jq .issue_dependencies_summary.blocked_by
gh issue list --label in-progress --state open --json number --jq length
```

Go on only when all three hold. Otherwise report which one failed and stop:

- the issue is open, not labelled `in-progress`, and assigned to nobody else
- `blocked_by` is `0`: every blocker is closed
- fewer than 3 issues are `in-progress`: open PRs wait on one human reviewer

## 2. Claim it

```bash
gh issue edit N --add-assignee @me --add-label in-progress
```

The `in-progress` label is the claim: any session running step 1 now sees the issue taken.

## 3. Enter the worktree

Call `EnterWorktree` with name `issue-N`. It fetches, then branches `worktree-issue-N` from the latest `origin/main` into `.claude/worktrees/issue-N/`.

The name stays exactly `issue-N`: the tests and `db/dev-setup.sh` derive the database name `openpgx_test_issue-N` from it.

## 4. Create the test database

```bash
PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=postgres conda run -n pg-client ./db/dev-setup.sh issue-N
```

This creates `openpgx_test_issue-N` and applies `db/migrations/` to it alone. Re-run it whenever this branch adds or changes a migration. The shared `openpgx` and `openpgx_test` never see this branch's migrations.

## 5. Run the baseline

```bash
conda run -n gwas-env python -m unittest discover -s tests 2>&1 | grep -E '^(Ran|OK|FAILED)'
```

Green is `Ran <n> tests` followed by a bare `OK`. `OK (skipped=…)` is red: the database tests skipped (missing database or wrong Python), so almost nothing ran.

Use this same command for every test run in this issue. Report the baseline, then implement. When the work is done, run `/finish-issue`.
