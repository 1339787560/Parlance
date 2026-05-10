# Roles & Development Guide

## Role Definitions
| Role | Responsibility | Tech/Lang |
|:---|:---|:---:|
| **LUA-Client-DEV-xzmp** | Maintain legacy Cocos-2DX client | Lua |
| **Creator-Client-DEV-xzmp** | Maintain new CocosCreator 3.8.1 client | TS |
| **CPP-GameSVR-DEV-xzmp** | Maintain GameSvr & legacy gift services | C++ |
| **CP-DEV-xzmp** | Maintain new gift services, user plugins & reward logic | TS |

## Working Rules
1. **L0 Required**: Must read L0 docs (duties, dir priority, index).
2. **Directory Isolation**: Only access your own role directory.
3. **Cross-Project Access**: Accessing other roles' code → spawn a Subagent (load docs → read code → return result).

## Development Pipeline

### LUA-Client-DEV-xzmp

Legacy maintenance only — no new development. Query historical functionality as needed.

### Common Development Flow (Creator / CPP / CP)

Applies to all active development roles.

```
Write proto doc (requirements) → Establish BDD → Determine: incremental on existing module or new module?
→ TDD: derive implementation doc from BDD (untestable design = bad design)
→ Follow existing patterns, minimal increment, test-first
→ Run tests: new features pass + existing features regress-free
→ Generate L3 doc from implementation doc → sync upward through L2 → L1 → L0
```

Key principles:
- **Proto first**: Guide the player to write a prototype spec before any code.
- **BDD drives design**: Behavior scenarios define what to test; if you can't test it, redesign.
- **Test-first always**: Write failing test → confirm failure → minimal implementation → confirm pass → refactor.
- **Minimal increment**: Follow existing code conventions; add only what's needed.
- **Doc sync bottom-up**: After implementation, generate L3 from the implementation doc, then update L2, L1, L0 in order.

---

# Knowledge Base Guide

> Core principle: **tiered indexing, load on demand, never scan everything**.

## Note Hierarchy

| Tier | Filename | Role | Size |
|------|----------|------|------|
| L0 | `L0_Index.md` | Global index — tech stack, responsibilities, path index to L1/L2 | < 500 lines |
| L1 | `L1_<Module>.md` | Module map — responsibility boundaries, file summaries, glossary | < 300 lines |
| L2 | `L2_<Feature>.md` | Deep logic — state transitions, data structures, pitfalls | Unlimited |

## Load Strategy
1. Load `L0_Index.md` by default
2. Locate relevant L1/L2 by problem domain, load by path
3. Read source code only when notes are insufficient

## L1 Generation (Two Phases)

**Phase A**: Run `python skills/file_indexer.py <path> <extensions>` → get file map → write skeleton to L1.

**Phase B**: Batch files (≤15 per batch), launch parallel sub-agents for ≤100-char summaries, **write each result immediately** (never batch deliver).

## Incremental Sync

| Change Type | Action |
|-------------|--------|
| New concept | Update L1 glossary |
| Bug fix (subtle) | Add to L2 Known Issues (symptoms → root cause → solution → prevention) |
| Architecture change | Update L0 + affected L1 |

---

# Bootstrapping New Project Docs

## Phase 0: Discovery (30-60 min)

Walk top-level dirs → read entry point → read configs → check deps → skim README. Output: one-liner purpose, tech stack, dir manifest, key files.

## Phase 1: Create L0 (20-40 min)

Fill template: Purpose (one sentence) → Tech stack → Dir map → Core concepts (project jargon) → L1 module index → Architecture conventions (naming, paths, config, errors).

## Phase 2: Generate L1 (15-30 min each, on demand)

Pick 3-5 most-used modules. For each: Phase A (file skeleton) → Phase B (parallel summaries). Priority: recently worked on > common debug targets > stable rarely-changed.

## Phase 3: Validate & Maintain

- Newcomer can grasp project from L0 in ≤10 min?
- L0→L1→L2 links work?
- Paths still accurate?

| Trigger | Where | Action |
|---------|-------|--------|
| New module/dir | L0 | Add row; create L1 |
| New concept | L0 + L1 | Append term |
| Architecture change | L0 + affected L1 | Revise |
| Hard bug | L2 | Log under Known Issues |
| File rename/move | L1 | Update path |