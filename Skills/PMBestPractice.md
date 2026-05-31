# API Best Practices (Agent-Oriented)

`http://host:8787/api` (vite dev → `127.0.0.1:8787`)

## Core: Read-Revise-Commit

```
GET /api/snapshot → state {revision=R}
mutate locally
POST/PUT/DELETE {baseRevision:R}
409 → re-GET, re-apply, retry
200 → done
```

---

## Data Model

```ts
// Snapshot (GET /api/snapshot, POST /api/import body)
{ versions: Version[], tasks: Task[], assignees: string[], projects: string[],
  revision: number, updatedAt: string }

// Version — name REQUIRED (400 if empty); status defaults "未开始"
{ id: string, name: string, group: string, status: "未开始"|"进行中"|"已完成"|"已暂停",
  startDate: string, endDate: string, createdAt: string }

// Task — name REQUIRED; priority defaults "P2", status "未开始"
// parentId undefined = top-level, ""→undefined, non-empty = FK to tasks.id (subtask)
// parentHours auto-calc = sum(child estimatedHours/actualHours) — DON'T set parent hours directly
{ id: string, versionId: string, parentId?: string, name: string, assignee: string,
  startDate: string, completedDate?: string, estimatedHours: number, actualHours: number,
  status: "未开始"|"进行中"|"已完成"|"已暂停", project: string, priority: "P0"|"P1"|"P2"|"P3",
  createdAt: string }
```

---

## Endpoints

All writes require `{baseRevision}`. E.g. POST /api/tasks: `{baseRevision, name, ...}`.

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/snapshot` | 200 + Snapshot |
| GET | `/api/events` | SSE (see below) |
| GET | `/api/logs?limit=N` | 200 + operation_log[] |
| GET | `/api/history?limit=N` | 200 + {revision, operation, created_at}[] |
| POST | `/api/versions` | 201 + Version ← `{baseRevision, name, group?, status?, startDate?, endDate?}` |
| PUT | `/api/versions/:id` | 200 + Version ← partial fields |
| DELETE | `/api/versions/:id` | 200 + `{ok: true}` — cascades: removes all tasks under version |
| POST | `/api/tasks` | 201 + Task ← `{baseRevision, name, versionId?, parentId?, assignee?, startDate?, completedDate?, estimatedHours?, actualHours?, status?, project?, priority?}` |
| PUT | `/api/tasks/:id` | 200 + Task ← partial fields — auto-updates assignee/project lists |
| DELETE | `/api/tasks/:id` | 200 + `{ok: true}` — cascades: removes descendant subtasks; recalc parent hours |
| POST | `/api/assignees` | 200 + string[] |
| POST | `/api/projects` | 200 + string[] |
| POST | `/api/import` | 200 + Snapshot — atomic overwrite of all arrays |
| POST | `/api/rollback` | 200 + Snapshot ← `{baseRevision, revision: N}` |

> Body limit: 1MB. Bad fields: 400 "name required". Bad path: 404. Parse/server error: 500.

---

## Concurrency

Revision-based optimistic lock. Each write bumps revision. Must pass current revision.

409 body: `{error: "...", currentRevision: N}` → re-GET /api/snapshot, re-apply changes, retry.

Chain sequential writes: each 200 response carries next revision for subsequent ops.

---

## SSE

```
GET /api/events → event: change  data: {"revision": N, "updatedAt": "..."}
```

Received `change` revision > local → GET /api/snapshot for fresh state, re-apply pending changes.

---

## Caveats

- No auth. CORS wide open.
- Snapshot DB: each write R/W full JSON. Not for high-frequency.
- DELETE version: kills ALL tasks under it. No soft delete.
- `startDate`/`endDate`: plain strings, no server validation.
- Import = full overwrite. Use for backup restore / bulk init.

---

## Recommended: [api.py](api.py) CLI Wrapper

`api.py` replaces raw curl/PowerShell. Handles UTF-8 and revision auto-management.

### Usage

```bash
# Snapshot
python api.py snapshot

# Revision
python api.py rev

# Version CRUD
python api.py version create "Sichuan Mahjong v20.6" -d 2026-05-20
python api.py version delete <id>

# Parent task (no --parent)
python api.py task create "Data Migration" -v <versionId>

# Subtask (--parent set)
python api.py task create "chunksvr add API" -v <versionId> -p <parentId> -a "CPP-GAMESVR-DEV" -H 1

# List tasks for version
python api.py tasks <versionId>

# Update / delete
python api.py task update <taskId> --status "进行中"
python api.py task delete <taskId>
```

### Options

| Flag | Alias | Purpose | Example |
|------|-------|---------|---------|
| `--version` | `-v` | Version ID | `-v mpo9xxx` |
| `--parent` | `-p` | Parent task ID | `-p mpo9yyy` |
| `--assignee` | `-a` | Assignee | `-a "CP-DEV"` |
| `--hours` | `-H` | estimatedHours | `-H 1.5` |
| `--status` | `-s` | Status | `-s "进行中"` |
| `--priority` | `-P` | Priority | `-P P1` |
| `--start-date` | `-d` | Start date | `-d 2026-05-30` |

### Why api.py

- **UTF-8 safe**: Python native UTF-8, no Windows encoding issues
- **Auto revision**: GETs fresh revision before each write
- **Auto 409 retry**: retries once on conflict
- **Zero deps**: stdlib only, no pip install

### Chained Writes

Each call independently fetches revision — no 409 risk:

```bash
python api.py task create "Task A" -v $VID -p $PID -a "CP-DEV" -H 1
python api.py task create "Task B" -v $VID -p $PID -a "Creator-Client-Dev" -H 0.5
```

---

## Pitfalls

### 1. Windows curl Chinese Encoding

curl on Windows (both PowerShell and Git Bash) sends Chinese text as GBK, not UTF-8. Server parses as UTF-8 → garbled storage.

| Env | Encoding | Symptom |
|-----|----------|---------|
| PowerShell `curl.exe` | GBK | Stored garbled, reads as `????` |
| Git Bash `curl` | GBK | Stored garbled, reads as `CP ������¼Ǩ�ƹ���` |
| Python `urllib.request` | UTF-8 ✅ | Correct |

Fix: use `python api.py`. Never use curl for Chinese text on Windows.

### 2. Revision Chain Conflicts

Each write bumps server revision. Sequential writes must use fresh revision each time.

```bash
# Wrong: same revision for all
POST ... {baseRevision:7, task1}  # ok → rev=8
POST ... {baseRevision:7, task2}  # 409 (current rev=8)

# Right: fetch latest before each write
r = GET /api/snapshot → revision
POST ... {baseRevision:r, ...}
r = GET /api/snapshot → revision
POST ... {baseRevision:r, ...}
```

`api.py` handles this automatically.

### 3. Parent Hours Auto-Sum

Parent task `estimatedHours` = sum of child subtask hours. Server auto-calculates.

- Setting parent `estimatedHours` directly has no effect
- Adding/removing subtasks auto-recalculates parent hours

### 4. Delete Cascade

- `DELETE /api/versions/:id` → removes ALL tasks under version (irreversible)
- `DELETE /api/tasks/:id` → removes all descendant subtasks; recalculates parent hours

### 5. PowerShell $pid Reserved

`$pid` is a read-only process ID variable in PowerShell. Cannot use as parameter name.

```powershell
# Error: Cannot overwrite variable pid because it is read-only
function New-Task($pid) { }

# Fix: use $ptId or $parentId
function New-Task($ptId) { }
```
