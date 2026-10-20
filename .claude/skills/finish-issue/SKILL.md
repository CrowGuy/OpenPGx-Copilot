---
name: finish-issue
description: Finish a GitHub issue started with /start-issue. Opens its PR once the implementation is done, or cleans up its worktree and test database once the PR has merged.
---

# Finish an issue

Argument: the issue number `N`. Two branches:

- the implementation is done and has no PR yet → **A. Open the PR**
- the PR has merged → **B. Clean up**

Write every command literally, one command per call; tools come from the conda envs in `/start-issue`'s prerequisites. The test command and its green criterion are step 5 of `/start-issue`.

## A. Open the PR

1. Bring the branch up to date:

   ```bash
   git fetch origin
   git rebase origin/main
   ```

   Resolve conflicts with the `resolving-merge-conflicts` skill.

2. Check the numbered files. Every number in `db/migrations/` and `docs/adr/` must be unique after the rebase. If `main` took a number this branch also used, rename this branch's file to the next free number and update its references. After any migration change, re-run step 4 of `/start-issue`.

3. Run the full suite. Green is a bare `OK`; anything else, fix it and run again.

4. Push. The remote branch keeps the local name `worktree-issue-N`, so the plain `git push` of step 6 works:

   ```bash
   git push -u origin HEAD
   ```

5. Open the PR. Match the title and body style of recent PRs (`gh pr list --state merged --limit 5`). The body ends with `Closes #N`.

   ```bash
   gh pr create --base main --head worktree-issue-N --title "<title>" --body-file <file>
   ```

6. Report the PR URL. Keep the worktree, the database and the `in-progress` label: review fixes happen in this worktree. Push fixes with plain `git push`. A PR rebased during review needs `git push --force-with-lease`; ask the user before running it.

## B. Clean up

1. Confirm the merge:

   ```bash
   gh pr view worktree-issue-N --json state --jq .state
   ```

   Go on only on `MERGED`.

2. Drop the test database:

   ```bash
   PGPASSWORD=postgres conda run -n pg-client psql -h 127.0.0.1 -U postgres -d openpgx -c 'DROP DATABASE IF EXISTS "openpgx_test_issue-N" WITH (FORCE)'
   ```

3. Release the claim: `gh issue edit N --remove-label in-progress`. The merge closed the issue through `Closes #N`; check with `gh issue view N --json state` and close it if it is still open.

4. Remove the worktree and its branch. Uncommitted files in it exist nowhere else: if `git status --porcelain` in the worktree lists any, show them to the user and wait.
   - **This session entered it through `/start-issue`:** call `ExitWorktree` with `action: remove`. If it refuses over commits missing from the original branch, the merge confirmed in step 1 covers them: call it again with `discard_changes: true`.
   - **Any other session**, from the main checkout:

     ```bash
     git worktree remove .claude/worktrees/issue-N
     git branch -D worktree-issue-N
     ```
