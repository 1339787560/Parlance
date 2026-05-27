# PM 任务管理系统 API 最佳实践

> 系统名称：版本任务管理系统（Version Task Manager）
> 后端 API：http://192.168.46.166:8787
> 前端 UI：http://192.168.46.166:5173

---

## 1. API 概览

所有端点均位于 `http://192.168.46.166:8787` 下：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/snapshot | 获取全量快照（版本、任务、负责人、项目、revision） |
| POST | /api/versions | 创建版本 |
| PUT | /api/versions/:id | 更新版本 |
| DELETE | /api/versions/:id | 删除版本 |
| POST | /api/tasks | 创建任务（支持 parentId 实现子任务） |
| PUT | /api/tasks/:id | 更新任务 |
| DELETE | /api/tasks/:id | 删除任务 |
| POST | /api/assignees | 添加负责人 |
| POST | /api/projects | 添加项目 |
| GET | /api/events | SSE 实时同步事件流 |

---

## 2. 数据模型

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

### Task（任务）

```json
{
  "id": "uuid",
  "versionId": "uuid",
  "parentId": "uuid | null",
  "name": "实现登录功能",
  "assignee": "张三",
  "startDate": "2026-01-15",
  "completedDate": "2026-02-01 | null",
  "estimatedHours": 16,
  "actualHours": 14,
  "status": "已完成",
  "project": "用户中心",
  "priority": "P0",
  "createdAt": "2026-01-10T00:00:00Z"
}
```

**状态枚举：** `未开始` / `进行中` / `已完成` / `已暂停`

**优先级枚举：** `P0` / `P1` / `P2` / `P3`

---

## 3. 任务父子关系

系统通过 `parentId` 字段支持两级任务层级：

- **根任务（Root Task）：** `parentId` 为 `null` 或不存在
- **子任务（Child Task）：** 通过 `parentId` 指向父任务 ID
- **层级限制：** 仅支持两级（父 → 子），不支持多级嵌套

### 统计聚合规则

UI 统计栏对 **叶子任务（Leaf Tasks）** 进行 `estimatedHours` / `actualHours` 的汇总：

- **叶子任务 = 没有子任务的任务**（无论是根任务还是子任务，只要它本身没有孩子）
- **父任务的自身 estimatedHours 不被计入汇总**（即使父任务填了工时，也会被系统忽略）

### 删除级联

删除父任务时，前端会收集所有后代 ID 一并删除。调用方需自行处理级联逻辑。

---

## 4. Revision 并发控制

系统使用 revision 机制保证数据一致性：

### 核心规则

1. 每次调用 `GET /api/snapshot`，返回的响应中包含当前 `revision`（整数，从 0 开始递增）
2. 所有写操作（`POST` / `PUT` / `DELETE`）的 **请求体中必须包含 `baseRevision`** 字段
3. `baseRevision` 的值必须等于服务器当前的 revision
4. 每次成功的写操作会使服务器 revision **+1**
5. 如果 revision 不匹配，服务器返回：`"数据已被其他人修改，请刷新后再保存"`

### 链式写入策略

当需要连续执行多个写操作时（如创建版本后批量创建任务），按以下步骤进行：

```
1. GET /api/snapshot        → 获取当前 revision = N
2. POST /api/tasks (baseRevision=N)          → 成功，revision → N+1
3. POST /api/tasks (baseRevision=N+1)        → 成功，revision → N+2
4. POST /api/tasks (baseRevision=N+2)        → 成功，revision → N+3
...
```

**每次写操作后 baseRevision 递增 1**，不得重复使用同一个 baseRevision。

---

## 5. 中文编码处理

在 curl/bash 环境下发送含中文的 JSON 时，**禁止**直接在字符串中嵌入中文字符（bash 可能无法正确编码 UTF-8）。

### 正确做法：使用 jq 构造 JSON

```bash
# 正确：使用 jq 构造 JSON
jq -n --arg n "登录功能" '{name: $n, status: "未开始"}' | \
  curl -X POST http://192.168.46.166:8787/api/tasks \
    -H "Content-Type: application/json" \
    -d @-
```

```bash
# 另一种正确做法：先写入文件再 curl
jq -n --arg n "登录功能" '{name: $n}' > /tmp/task.json
curl -X POST http://192.168.46.166:8787/api/tasks \
  -H "Content-Type: application/json" \
  -d @/tmp/task.json
```

### 错误做法

```bash
# 错误：直接嵌入中文字符
curl -X POST http://192.168.46.166:8787/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "登录功能"}'  # 可能编码错误！
```

---

## 6. 最佳实践流程

### 6.1 完整工作流：创建版本并添加任务

```bash
#!/bin/bash
BASE_URL="http://192.168.46.166:8787/api"

# Step 1: 获取当前 revision
SNAPSHOT=$(curl -s "$BASE_URL/snapshot")
REV=$(echo "$SNAPSHOT" | jq -r '.revision')
echo "Current revision: $REV"

# Step 2: 创建版本
VER_RESP=$(jq -n \
  --arg n "v2.0.0" \
  --arg g "核心功能" \
  --arg s "进行中" \
  --arg sd "2026-06-01" \
  --arg ed "2026-08-31" \
  --argjson r "$REV" \
  '{name: $n, group: $g, status: $s, startDate: $sd, endDate: $ed, baseRevision: $r}' | \
  curl -s -X POST "$BASE_URL/versions" -H "Content-Type: application/json" -d @-)
REV=$((REV + 1))

# Step 3: 获取版本 ID
VERSION_ID=$(echo "$VER_RESP" | jq -r '.id')

# Step 4: 创建任务（使用递增的 revision）
for task_name in "登录功能" "支付模块" "消息通知"; do
  jq -n \
    --arg vid "$VERSION_ID" \
    --arg n "$task_name" \
    --argjson r "$REV" \
    '{versionId: $vid, name: $n, status: "未开始", priority: "P1", estimatedHours: 8, baseRevision: $r}' | \
    curl -s -X POST "$BASE_URL/tasks" -H "Content-Type: application/json" -d @-
  REV=$((REV + 1))
done

echo "All done! Final revision: $REV"
```

### 6.2 创建父子任务

```bash
#!/bin/bash
BASE_URL="http://192.168.46.166:8787/api"
SNAPSHOT=$(curl -s "$BASE_URL/snapshot")
REV=$(echo "$SNAPSHOT" | jq -r '.revision')

# 假设已有 versionId，创建父任务
PARENT_RESP=$(jq -n \
  --arg vid "版本ID" \
  --arg n "用户中心" \
  --argjson r "$REV" \
  '{versionId: $vid, name: $n, status: "进行中", priority: "P0", baseRevision: $r}' | \
  curl -s -X POST "$BASE_URL/tasks" -H "Content-Type: application/json" -d @-)
REV=$((REV + 1))
PARENT_ID=$(echo "$PARENT_RESP" | jq -r '.id')

# 创建子任务（父任务自身不填工时，子任务填工时）
for child in "登录页面" "注册页面" "密码重置"; do
  jq -n \
    --arg vid "版本ID" \
    --arg pid "$PARENT_ID" \
    --arg n "$child" \
    --argjson r "$REV" \
    '{versionId: $vid, parentId: $pid, name: $n, status: "未开始", estimatedHours: 4, baseRevision: $r}' | \
    curl -s -X POST "$BASE_URL/tasks" -H "Content-Type: application/json" -d @-
  REV=$((REV + 1))
done
```

### 6.3 更新任务状态

```bash
# 获取最新 snapshot
SNAPSHOT=$(curl -s http://192.168.46.166:8787/api/snapshot)
REV=$(echo "$SNAPSHOT" | jq -r '.revision')
TASK_ID="任务ID"

# 更新任务为"已完成"
jq -n \
  --arg s "已完成" \
  --arg cd "2026-05-27" \
  --argjson r "$REV" \
  '{status: $s, completedDate: $cd, baseRevision: $r}' | \
  curl -s -X PUT "http://192.168.46.166:8787/api/tasks/$TASK_ID" \
    -H "Content-Type: application/json" -d @-
```

### 6.4 删除任务（含级联）

删除父任务时需手动收集所有子任务 ID：

```bash
SNAPSHOT=$(curl -s http://192.168.46.166:8787/api/snapshot)
REV=$(echo "$SNAPSHOT" | jq -r '.revision')
PARENT_ID="父任务ID"

# 查找所有子任务
CHILD_IDS=$(echo "$SNAPSHOT" | jq -r --arg pid "$PARENT_ID" '.tasks[] | select(.parentId == $pid) | .id')

# 先删子任务
for cid in $CHILD_IDS; do
  curl -s -X DELETE "http://192.168.46.166:8787/api/tasks/$cid" \
    -H "Content-Type: application/json" \
    -d "{\"baseRevision\": $REV}"
  REV=$((REV + 1))
done

# 再删父任务
curl -s -X DELETE "http://192.168.46.166:8787/api/tasks/$PARENT_ID" \
  -H "Content-Type: application/json" \
  -d "{\"baseRevision\": $REV}"
```

---

## 7. 实时同步

前端通过 SSE（Server-Sent Events）监听 `/api/events` 端点实现实时更新：

```javascript
const eventSource = new EventSource('http://192.168.46.166:8787/api/events');
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Data updated:', data);
  // 自动刷新 UI
};
```

**注意：** 每次写操作后建议主动调用 `GET /api/snapshot` 确认变更结果，因为 SSE 可能存在短暂延迟。

---

## 8. 常见问题与注意事项

| 问题 | 解决方案 |
|------|----------|
| `"数据已被其他人修改"` | 重新 GET /api/snapshot 获取最新 revision 后重试 |
| 中文乱码 | 使用 jq 构造 JSON，不要直接嵌入中文字符串 |
| 删除父任务后子任务残留 | 手动收集所有后代 ID 逐级删除 |
| revision 不连续 | 链式写入时每次操作后手动递增 baseRevision |
| 父任务工时未计入汇总 | 正常行为，系统只聚合叶子节点的工时 |

---

## 9. 快速参考

```bash
# 1. 获取 snapshot
curl -s http://192.168.46.166:8787/api/snapshot | jq '.revision'

# 2. 创建版本（jq 方式）
jq -n --arg n "v1.0" --argjson r 0 '{name: $n, baseRevision: $r}' | \
  curl -s -X POST http://192.168.46.166:8787/api/versions -H "Content-Type: application/json" -d @-

# 3. 创建任务
jq -n --arg vid "版本ID" --arg n "任务名" --argjson r 1 \
  '{versionId: $vid, name: $n, baseRevision: $r}' | \
  curl -s -X POST http://192.168.46.166:8787/api/tasks -H "Content-Type: application/json" -d @-

# 4. 查询所有任务
curl -s http://192.168.46.166:8787/api/snapshot | jq '.tasks'
```
