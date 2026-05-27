# PM 任务管理系统工作流

> **目标服务：** http://192.168.46.166:8787（API）/ http://192.168.46.166:5173（UI）
> **系统名称：** 版本任务管理系统（Version Task Manager）

---

## 一、API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/snapshot` | 获取全量快照（版本、任务、负责人、项目、revision） |
| POST | `/api/versions` | 创建版本 |
| PUT | `/api/versions/:id` | 更新版本 |
| DELETE | `/api/versions/:id` | 删除版本 |
| POST | `/api/tasks` | 创建任务（支持 `parentId` 子任务） |
| PUT | `/api/tasks/:id` | 更新任务 |
| DELETE | `/api/tasks/:id` | 删除任务 |
| POST | `/api/assignees` | 添加负责人 |
| POST | `/api/projects` | 添加项目 |
| GET | `/api/events` | SSE 实时同步事件流 |

---

## 二、数据模型

### Version（版本）

```json
{
  "id": "uuid",
  "name": "v1.0.0",
  "group": "核心功能",
  "status": "进行中",
  "startDate": "2026-01-01",
  "endDate": "2026-03-31",
  "createdAt": "2026-01-01T00:00:00Z"
}
```

状态：`未开始` / `进行中` / `已完成`

### Task（任务）

```json
{
  "id": "uuid",
  "versionId": "uuid",
  "parentId": "uuid | null",
  "name": "任务名",
  "assignee": "李真",
  "startDate": "2026-01-15",
  "completedDate": "2026-02-01 | null",
  "estimatedHours": 8,
  "actualHours": 6,
  "status": "已完成",
  "project": "项目名",
  "priority": "P0"
}
```

| 字段 | 说明 |
|------|------|
| `parentId` | 非空则视为子任务。父任务的工时 = 子任务工时自动求和（UI 显示 Σ 标记） |
| `status` | 枚举：`未开始` / `进行中` / `已完成` / `已暂停` |
| `priority` | 枚举：`P0` / `P1` / `P2` / `P3` |
| `estimatedHours` | 单位：天。前端显示为 `Xd` |
| `baseRevision` | **每次写操作必须携带**，值为当前服务器 revision |

---

## 三、Revision 并发控制

**每次写操作（POST/PUT/DELETE）请求体中必须携带 `baseRevision` 字段。**

```json
{ "baseRevision": 42, ... }
```

规则：
1. `GET /api/snapshot` → `revision` 为当前值
2. 每次**成功**的写操作使 revision +1
3. 链式写入时，每次 increment 1：

```bash
REV=$(curl -s http://192.168.46.166:8787/api/snapshot | jq '.revision')
# 创建任务 1, baseRevision=$REV  → 成功, REV=$((REV+1))
# 创建任务 2, baseRevision=$REV  → 成功, REV=$((REV+1))
```

---

## 四、中文编码（重要）

禁止在 curl 命令的 `-d '...'` 中直接嵌入中文字符。**必须使用 jq 构造 JSON：**

```bash
# ✅ 正确
jq -n --arg n "登录功能" '{name: $n}' | \
  curl -X POST http://192.168.46.166:8787/api/tasks \
    -H "Content-Type: application/json" -d @-

# ✅ 也可写入文件再 curl
jq -n --arg n "登录功能" '{name: $n}' > /tmp/task.json
curl -X POST http://192.168.46.166:8787/api/tasks \
  -H "Content-Type: application/json" -d @/tmp/task.json
```

---

## 五、工作流：任务生命周期管理

### 5.1 拉取项目进度

```bash
curl -s http://192.168.46.166:8787/api/snapshot | jq '{revision, versions: [.versions[] | {name, group, status}], taskCount: (.tasks | length)}'
```

本地缓存建议：写入 `_pm_cache.json`，每次操作前比对 revision 判断是否需要刷新。

### 5.2 版本状态判断

获取 snapshot 后，检查版本的 `status`：

- `已完成` → 提示用户是否要新增版本、拆分任务
- `未开始` / `进行中` → 按角色拆分任务到该版本

### 5.3 任务拆分规范

按角色（Role）拆分任务，每个任务标注具体执行人（负责人）：

| 角色 | 职责 | 典型负责人 |
|------|------|-----------|
| CP-DEV-xzmp | 后端 CP 服务 | 李真 |
| CPP-GameSVR-DEV-xzmp | 游戏服务端 | 李真 |
| Creator-Client-DEV-xzmp | CocosCreator 客户端 | 李真 |
| LUA-Client-DEV-xzmp | Lua 客户端维护 | 李真 |

拆分完毕时，提示用户：**"当前版本{version}的进度：{已完成}/{总数}，是否继续？"**

### 5.4 开发开始

当用户开始一项开发任务时：
1. 获取 snapshot，找到当前任务在 PM 系统中的位置
2. 检查该任务状态是否为 `进行中`，如不是则提示用户更新状态
3. 绑定到会话上下文：`currentTaskId`、`currentVersionId`

### 5.5 开发完成

当用户完成一项开发任务时：
1. 获取 snapshot，定位任务
2. 检查从上一个标记的位置到当前任务之间是否有其他`进行中`任务
3. 提示用户：**"从{上一步}到{当前}之间的任务是否需要标记为已完成？"**

---

## 六、父子任务规划策略

```
父任务（不填工时，显示 Σ 自动汇总）
├── 子任务 1（填 estimatedHours）
├── 子任务 2（填 estimatedHours）
└── 子任务 3（填 estimatedHours）
```

- 父任务的 `estimatedHours` 应填 `0`，系统自动求和显示 Σ 标记
- 叶子节点的工时总和在 UI 统计栏展示
- 支持两级层级（父→子），不支持多级嵌套

---

## 七、创建版本示例

```bash
# 获取 revision
REV=$(curl -s http://192.168.46.166:8787/api/snapshot | jq '.revision')

# 创建川麻版本
jq -n --arg n "21.3" --arg g "川麻" --arg s "未开始" --arg sd "2026-06-01" --arg ed "2026-06-15" --argjson r "$REV" \
  '{name: $n, group: $g, status: $s, startDate: $sd, endDate: $ed, baseRevision: $r}' | \
  curl -s -X POST http://192.168.46.166:8787/api/versions \
    -H "Content-Type: application/json" -d @-
```

---

## 八、创建父子任务示例

```bash
SNAPSHOT=$(curl -s http://192.168.46.166:8787/api/snapshot)
REV=$(echo "$SNAPSHOT" | jq '.revision')
VERSION_ID=$(echo "$SNAPSHOT" | jq -r '.versions[0].id')  # 取第一个版本

# 1. 创建父任务
PARENT=$(jq -n --arg vid "$VERSION_ID" --arg n "客户端改造" --arg a "李真" --arg d "2026-06-01" --argjson r "$REV" \
  '{versionId: $vid, name: $n, assignee: $a, startDate: $d, estimatedHours: 0, status: "未开始", project: "川麻", priority: "P1", baseRevision: $r}' | \
  curl -s -X POST http://192.168.46.166:8787/api/tasks \
    -H "Content-Type: application/json" -d @-)
REV=$((REV + 1))
PARENT_ID=$(echo "$PARENT" | jq -r '.id')

# 2. 创建子任务
for child_name in "登录页面改造" "支付模块更新" "消息通知优化"; do
  jq -n --arg vid "$VERSION_ID" --arg pid "$PARENT_ID" --arg n "$child_name" --arg a "李真" --arg d "2026-06-01" --argjson e 2 --argjson r "$REV" \
    '{versionId: $vid, parentId: $pid, name: $n, assignee: $a, startDate: $d, estimatedHours: $e, status: "未开始", project: "川麻", priority: "P1", baseRevision: $r}' | \
    curl -s -X POST http://192.168.46.166:8787/api/tasks \
      -H "Content-Type: application/json" -d @-
  REV=$((REV + 1))
done

echo "创建完成，最终 revision: $REV"
```

---

## 九、快速查询

```bash
# 版本列表
curl -s http://192.168.46.166:8787/api/snapshot | jq '[.versions[] | {name, group, status}]'

# 指定版本的任务
curl -s http://192.168.46.166:8787/api/snapshot | jq '[.tasks[] | select(.versionId=="VERSION_ID") | {name, assignee, status, est: .estimatedHours}]'

# 当前 revision
curl -s http://192.168.46.166:8787/api/snapshot | jq '.revision'

# 任务统计（按负责人）
curl -s http://192.168.46.166:8787/api/snapshot | jq '[.tasks[] | group_by(.assignee)[] | {assignee: .[0].assignee, total: length, done: map(select(.status=="已完成")) | length}]'
```
