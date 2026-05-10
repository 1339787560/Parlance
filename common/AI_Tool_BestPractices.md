# AI Tool Best Practices

> Core practices from superpowers + gstack, distilled as role working standards.
> **Load this file only when**: discussing prototype/spec docs, or starting code implementation.

## Iron Laws

1. **Skill-First**: Invoke a skill if there's even a 1% chance it applies. Process skills (brainstorming/debugging) before implementation skills. Priority: user instructions > skills > default behavior.
2. **Design Before Code**: No code without approved design, no matter how "simple". Flow: explore context → ask clarifying questions → propose 2-3 options → present design in sections → write spec → self-review → user review → write plan.
3. **No Fix Without Root Cause**: Never patch symptoms. Treating symptoms = failure. 3 failed fix attempts → question the architecture.
4. **Evidence Before Claims**: Don't claim done without running verification. "Should pass" ≠ passed.
5. **No Production Code Without Failing Test**: Write failing test → confirm failure → write minimal implementation → confirm pass → refactor. Writing tests after code ≠ TDD.

## Debugging Four Stages

| Stage | Activity | Standard |
|-------|----------|----------|
| Root Cause Investigation | Read error messages, stable reproduction, check recent changes, gather evidence layer by layer | Understand WHAT + WHY |
| Pattern Analysis | Find working examples, diff against broken | Identify all differences |
| Hypothesis Testing | Single hypothesis, minimal change, one variable at a time | Confirm or refute |
| Implementation | Write regression test first → fix root cause → verify | Bug resolved, tests pass |

## Plan Norms

- Steps = 2-5 min single actions (write test → confirm fail → implement → confirm pass → commit)
- No placeholders (TBD/TODO/"fill in later"/"similar to Task N")
- Must include: exact paths, complete code, exact commands + expected output
- Self-review: spec coverage + placeholder scan + type consistency

## Engineering Norms

- **Completion Status**: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT
- **Confusion Protocol**: High-risk ambiguity → stop → name it in one sentence → 2-3 options + trade-offs → ask user
- **Voice**: Direct and specific, builder to builder. No AI crutch words (delve/crucial/robust/comprehensive/nuanced/multifaceted). No em dashes. Tie technical choices to user impact.
- **Dedicated Tools Over Bash**: Read/Edit/Write/Glob/Grep over cat/sed/find/grep
- **Todo Discipline**: Mark items complete one by one, never batch-mark
- **Think Before Heavy Actions**: Briefly state approach before complex operations, let user correct cheaply

## Skill Routing

| Scenario | Skill |
|----------|-------|
| New ideas/brainstorming | `/office-hours` |
| Bug/errors/abnormal behavior | `/investigate` |
| QA/testing website behavior | `/qa` |
| Code review/diff check | `/review` |
| Merge/push/create PR | `/ship` |
| QA browser testing | `/browse` — use `$B` binary, disable `mcp__claude-in-chrome` |

## Git Workflow

- Before implementing, detect if already in isolated worktree (`GIT_DIR != GIT_COMMON`)
- Prefer platform-native tools (EnterWorktree); fall back to git worktree when unavailable
- Branch completion: verify tests → detect environment → four options (merge/create PR/keep/discard) → execute → only merge+discard cleans up worktree