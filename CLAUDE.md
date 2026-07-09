# Coding Agent Guidelines

These rules apply to every code change in this repository.

This repository follows a Superpowers-inspired SDLC workflow and Ponytail-inspired coding taste.

Use Superpowers as the process model: clarify the request, design when needed, plan the work, implement in small steps, verify with tests or checks, review the diff, and finish with a clear summary.

Use Ponytail as the implementation taste: prefer the smallest safe change, reuse existing code, avoid speculative abstractions, avoid unnecessary dependencies, and reduce total system complexity.

These are not rigid ceremonies. Scale the workflow to the size and risk of the task.

## Development Workflow

Use different workflow depth depending on task size.

### Tiny change

Examples: typo, copy change, small styling tweak, obvious one-line bug fix.

Workflow:

1. State the intended change.
2. Make the smallest safe edit.
3. Run the narrowest relevant check when feasible.
4. Summarize the diff.

Do not create a full design document or implementation plan for tiny changes.

### Normal change

Examples: small feature, bug fix, behavior change, test addition.

Workflow:

1. Clarify the request.
2. Convert the request into verifiable success criteria.
3. Inspect the existing code path before editing.
4. Propose the smallest safe implementation plan.
5. Identify the verification command or test.
6. Implement surgically.
7. Run relevant tests.
8. Review the diff for unnecessary code, abstractions, files, and dependencies.
9. Summarize changed files, risks, skipped checks, and follow-up work.

### Large or risky change

Examples: new feature area, data model change, auth/permission logic, migration, external integration, broad refactor.

Workflow:

1. Use a brainstorming/design phase before coding.
2. Present the design in small reviewable sections.
3. Wait for design approval before implementation.
4. Write an implementation plan with small tasks.
5. Prefer TDD where behavior can be specified with tests.
6. Use an isolated branch or worktree.
7. Run tests after each meaningful step.
8. Request code review before considering the work complete.
9. Finish the branch by summarizing what changed, what was verified, what remains risky, and whether to merge, keep, or discard.

## Operating Principles

1. Think before coding.

* State assumptions before implementing.
* Ask when requirements are ambiguous.
* Present tradeoffs when multiple interpretations exist.
* Prefer the simplest valid approach.
* Do not use planning as ceremony when the task is tiny.

2. Simplicity first.

* Implement only what was requested.
* Do not add speculative abstractions, options, or configuration.
* Avoid single-use abstractions.
* Prefer readable local code over generic helpers.
* Prefer existing project utilities over new utilities.
* Prefer standard library, platform APIs, and existing dependencies over new dependencies.
* If the implementation becomes large, look for a smaller design before continuing.

3. Surgical changes.

* Touch only files and lines required by the task.
* Do not refactor unrelated code.
* Match existing style.
* Remove only unused code introduced by your own change.
* Mention unrelated dead code instead of deleting it.

4. Goal-driven execution.

* Convert the request into verifiable success criteria.
* For bug fixes, reproduce the bug with a test before fixing when feasible.
* For new behavior, add or update tests when appropriate.
* Run the narrowest relevant checks first, then broader checks if needed.
* Do not claim completion without evidence.

## Ponytail-Inspired Implementation Ladder

Before adding code, stop at the first rung that works:

1. Does this need to exist?
2. Is the behavior already in this codebase?
3. Can existing project code be reused?
4. Can the standard library solve it clearly?
5. Can a native platform or framework feature solve it?
6. Can an existing dependency solve it?
7. Only then, write the minimum code that works.

Lazy about the solution. Never lazy about understanding the existing code.

Do not optimize for fewer lines. Optimize for lower total system complexity.

## Protected Boundaries

Never simplify away:

* validation
* authorization or permission checks
* data integrity
* migration safety
* privacy protections
* security checks
* accessibility
* error handling
* observability for critical flows
* tests that protect important behavior

If code is verbose because it protects one of these boundaries, preserve the boundary and make the intent clearer instead.

## Required Workflow

Before editing:

* Summarize the intended change.
* List assumptions or ambiguities.
* Identify existing code paths to inspect.
* Identify the verification command or test.

During editing:

* Keep the diff minimal.
* Do not improve adjacent code unless required.
* Do not add dependencies, new files, or abstractions without justification.

After editing:

* Run relevant tests or explain why they could not be run.
* Review the diff for over-engineering.
* Summarize changed files.
* Call out risks, skipped checks, or follow-up work.

## Self-Review Before Completion

Before reporting completion:

- Check whether the diff includes unnecessary files, abstractions, dependencies, or broad rewrites.
- Check whether tests or verification match the requested behavior.
- Check whether any protected boundary was weakened.
- Remove unnecessary code introduced by this change.
