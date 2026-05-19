# Role: {Role} — Docs Server: http://192.168.41.158:5080/

If `{Role}` is still the placeholder (not replaced with a real role name):
→ Ask user: "当前未指定角色。你想用哪个角色？" Options: CP-DEV-xzmp, CPP-GameSVR-DEV-xzmp, Creator-Client-DEV-xzmp, LUA-Client-DEV-xzmp
→ Once user picks, set `{Role}` = chosen role.

Rules:
1. Incomplete requirements → Ask immediately.
2. **Task Dispatch (mandatory, no skip regardless of task size)**:
   a. Identify file types this task touches (.cpp? .ts? .h? .md?)
   b. Re-fetch L0 → scan sections relevant to those file types
   c. **If .cpp/.h: MUST re-read Encoding section and use its gbk commands. NEVER use Edit/Write/Read tools.**
   d. Follow what L0 says — especially encoding rules, test commands, dev standards
   e. Only then proceed to code
3. No over-engineering; minimize new code.
4. Document fixes: Solve → Record at lowest level → Sync upward.
5. Prototype & implementation docs go in `{Role}/doc/` directory.
6. Before running tests → load BestPractices + re-fetch L0 "Test Execution" section. Never guess test commands.

**Red flag reminder**: "this task is simple" is exactly when you skip the check and miss critical rules. Task size is irrelevant. Always run Task Dispatch.

# Notes API

Base: `/api/a2a/` | Storage: `{workspace}/src/A2AFile/` | Write ops auto-commit.

| Action | Method | Path | Key Params | Git |
|:---:|:---:|:---|:---|:---:|
| List | GET | `/list` | `path` | ❌ |
| Read | GET | `/get` | `path` | ❌ |
| Create | POST | `/create` | `path`, `content`, `desc?` | ✅ |
| Update | POST | `/update` | `path`, `content`, `desc?` | ✅ |
| Delete | POST | `/delete` | `path`, `desc?` | ✅ |
| History | GET | `/history` | `path` | ❌ |
| Version | GET | `/version` | `path`, `hash` | ❌ |

`update` = full overwrite. `list` filters `.md`/`.py`/`.json` only. No locking. Response: `{ "success": bool, "message"?: string }`. Errors: 400 missing params, 403 path traversal, 404 not found.

# Boot Procedure

Base URL: `http://192.168.41.158:5000/api/a2a/` — use `curl` (WebFetch blocks LAN IPs).

Execute silently on first message — never announce boot steps or tell the user "L0 not loaded":

1. `curl GET /list` → discover role folders
2. `curl GET /get?path=COMMON.md` → shared rules & role definitions
3. `curl GET /get?path={Role}/L0_Index.md` → your role's L0 (Role = line 2)
4. From L0, load L1/L2 on demand via `/get`

Never hardcode paths. Directory isolation — own role only. Cross-role: serial default; use Subagent in CLI. On-demand loading — never fetch all. If context compressed and L0 lost → re-fetch silently, don't report to user.

## Cache Miss Protocol

Notes insufficient → read source code → extract findings → ask user "Update notes?" → if yes, write back to notes (lowest tier first, then sync upward).

Path: `POST /create` or `POST /update` via Notes API. Write immediately — never batch.

# Claude Commands & rtk

rtk hook auto-rewrites shell cmds (0 overhead). Debug: `rtk proxy <cmd>`.

## Slash Commands (no rtk — internal to Claude)

`/clear` `/compact` `/rewind` `/model` `/review` `/init` `/memory` `/cost` `/status` `/config` `/doctor` `/help` `/add-dir` `/permissions` `/exit`

## CLI Flags

`-p "query"` one-shot | `-c` continue | `-r <id>` resume | `--model` `--max-turns` `--allowedTools` `--permission-mode`

## Shell Commands (rtk-proxied)

`git status/diff/log/branch` `npm run` `ls` `cat/head` → all auto-proxied by rtk for token savings.

## rtk Meta

`rtk gain` `rtk gain --history` `rtk discover` `rtk proxy <cmd>`

# AI Tool Best Practices — Lazy Load

| Trigger | Action |
|---------|--------|
| Discussing prototype/spec docs | `curl GET /get?path=common/AI_Tool_BestPractices.md` |
| Implementing code based on a prototype doc | `curl GET /get?path=common/AI_Tool_BestPractices.md` |

Not loaded by default. Only load when discussing prototype docs or implementing from a spec. For direct code edits (simple changes, known fixes), skip — the Rules + L0 check above are sufficient.

Contents: Skill-first, design before code, TDD, root-cause debugging (4 stages), plan norms (no placeholders), engineering norms, skill routing, git worktree workflow.