# 数据迁移方案 — chunkSvr → CP

> 迁移范围：金币模块、迎新礼包剩余签到天数、荣耀特权等级和领取项记录、周月卡时间

---

## 数据映射关系

| chunkSvr 模块 | MySQL 表 | Redis Key | CP 目标模块 | 数据转换要点 |
|---------------|----------|-----------|------------|-------------|
| TQVip | `sqlas_tqvip` | `rdsas_tqvip:{userid}` | leveldefine | PB int32 → JSON；experience/grade/rewardstatus → 经验/等级/奖励领取状态 map |
| TQMonthCard | `sqlas_tqmonthcard` | `rdsas_tqmonthcard:{userid}` | cmmonthcard | PB int64 timenum → JSON 时间戳；monthcard/weekcard starttime/endtime/datetag |
| NewDeposit | `tblnewdeposit` | 无 | 无 | 单个 bigint → JSON number |
| TQNewPlayerDailyGift | `tbltqnewplayerdailygift` | 无 | cmnewplayerdailygift | remaindays/receivedays/awardday1-7 → JSON 签到剩余天数和领取记录；newplayer 资格标记 |

---

## 方案一：在线懒迁移（活跃玩家登录时触发）

### 流程

```
玩家登录 → CP OnLogon 回调
  → 检查迁移标记（Redis/MySQL）
  → 未迁移：HTTP POST chunkSvr /v1.0/chunkluareq
      → 查 VIP、月卡、金币、迎新礼包
      → PB解码 → JSON格式转换
      → async_internal_call 写入各目标模块
  → 标记已迁移
  → 正常响应客户端
```

### 代码增量

#### chunkSvr C++：0

HttpServerModule 已编译在 jinbi 分支二进制中，不需改 C++。

#### chunkSvr Lua：~100-130 行，5 文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `main.lua` (msgcenter) | 新增 `httpmain` + `httpreq` + `httpCallbacklist` + `registerhttp` 方法 | ~30 |
| `TQVip.lua` (msgcenter) | 新增 `registerhttp("querytqvip")` handler，调用 lasyncache.getcache 返回 VIP 数据 | ~30 |
| `TQMonthCard.lua` (msgcenter) | 新增 `registerhttp("querytqmonthcard")` handler | ~25 |
| `NewDeposit.lua` (msgcenter) | 新增 `registerhttp("querynewdeposit")` handler，直查 MySQL | ~20 |
| `TQNewPlayerDailyGift.lua` (msgcenter) | 新增 `registerhttp("querynewplayerdailygift")` handler，直查 MySQL | ~20 |

改动方式：纯新增，不修改已有业务逻辑。热重载生效，无需重编 C++。

#### CP：~200-300 行，1 新文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `convert_xzmp.ts`（新文件） | OnLogon 回调 → 检查标记 → HTTP 拉取 4 模块数据 → PB 解码 → 格式转换 → async_internal_call 分发写入各模块 → 标记完成 | ~200-300 |

为什么用单独文件而非改 4 个模块：
- 迁移是一次性逻辑，完成后脚本删除
- 需要协调 4 模块的拉取顺序和标记
- 不污染 4 个业务模块的生产代码
- async_internal_call 可写任意模块数据，不受"一个模块只能写自己数据库"约束

### 关键注意事项

- chunkSvr HTTP 入口（`httpmain`）需先补全，当前部署版本缺失
- 登录链路增加 ~15-35ms（HTTP 请求 + 数据转换 + 写入）
- 必须标记已迁移玩家，避免重复拉取
- chunkSvr 不可达时需降级（跳过迁移，使用默认值）
- PB 解码在 CP 端：CP 收到的是 chunkSvr Lua 返回的 JSON（Lua 侧已做 PB→table→JSON 转换），CP 不需要直接处理 PB 二进制

---

## 方案二：离线批量迁移（冷清时段直读数据库）

### 流程

```
停服或冷清时段
  → 触发 chunkSvr 脏队列刷盘（确保 MySQL 数据最新）
  → Python 脚本直连 chunkSvr MySQL + Redis
      → SELECT sqlas_tqvip / sqlas_tqmonthcard / tblnewdeposit / tbltqnewplayerdailygift
      → Redis 优先读（rdsas_tqvip:{uid} 等，拿更新数据）
      → PB 解码 → JSON 转换
  → 直连 CP MySQL + Redis
      → INSERT tblcpuserdata_leveldefine_xzmp 等
      → SET CP Redis key + EXPIRE
  → 全量完成，可验证
```

### 代码增量

#### chunkSvr C++：0

#### chunkSvr Lua：0

唯一操作：确保脏队列刷盘（手动触发或等 3 小时定时器自然刷盘）。

#### CP 业务模块：0

#### 迁移脚本：~300-400 行，1 新 Python 文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `convert_xzmp.py`（新文件） | 连接 chunkSvr MySQL + Redis → 连接 CP MySQL + Redis → PB 解码（proto2 版 proto） → 数据映射转换 → 批量写入 → 验证报告 | ~300-400 |

依赖：xzmpDB 已有 DBConnector.py、tqvip_pb2.py 可复用。但需换成 **proto2 版 proto** 编译的 pb2 文件（当前 xzmpDB 用 proto3 版本可能丢失零值字段）。

映射转换逻辑与方案一相同，批量处理更简单——无需考虑并发、标记、降级。

### 关键注意事项

- 必须先触发脏队列刷盘，确保 MySQL 数据完整
- Redis 优先读取（比 MySQL 更新），miss 则 fallback MySQL
- PB proto 版本：chunkSvr 用 proto2（`syntax = "proto2"`），xzmpDB 现有的 proto3 版本可能与零值字段不兼容，迁移脚本必须用 proto2 版本
- 批量写入可分批 commit，避免单次事务过大
- 写入前可先 SELECT 检查目标表是否已有数据，避免覆盖新数据

---

## 方案对比

| | 方案一（在线懒迁移） | 方案二（离线批量） |
|--|--|--|
| chunkSvr C++ | 0 | 0 |
| chunkSvr Lua | ~100-130 行，5 文件 | 0（仅手动触发刷盘） |
| CP 业务模块 | 0（新增独立脚本） | 0 |
| 新脚本 | convert_xzmp.ts ~200-300 行 | convert_xzmp.py ~300-400 行 |
| PB 处理 | chunkSvr Lua 内解码，CP 收 JSON | Python 用 proto2 版 pb2 文件解码 |
| 运行依赖 | chunkSvr HTTP 入口需先补全 | chunkSvr 需先刷盘 |
| 迁移完整性 | 仅迁移登录玩家 | 全量迁移 |
| 风险分散 | 单玩家出错影响小 | 批量出错影响大，可回滚验证 |
| 时机 | chunkSvr 还在线时，活跃玩家陆续触发 | chunkSvr 即将下线前，冷清时段一次性完成 |

---

## 建议执行顺序

**两者结合，不冲突：**

1. 先部署方案一的 chunkSvr Lua 改动（补 HTTP 入口），让活跃玩家逐步迁移
2. chunkSvr 下线前，用方案二兜底全量迁移未登录玩家
3. 代码增量总和约 ~500 行

---

## PB 版本兼容性说明

chunkSvr 原始 proto 文件使用 `syntax = "proto2"`，包含 `required/optional` 字段修饰符。

xzmpDB 现有的 tqvip.proto 使用 `syntax = "proto3"`（人为改写版），与原始 proto2 定义有差异：

- proto3 所有字段隐式 optional，零值字段编码时被省略
- proto2 的 `required` 字段在 proto3 中变成隐式 optional
- proto3 编码的二进制数据，proto2 解码器会因缺少 required 字段而报错

**迁移脚本必须使用 chunkSvr 原始 proto2 版 proto 文件编译 pb2，不能用 xzmpDB 的 proto3 版本。**

方案一中 PB 解码发生在 chunkSvr Lua 侧（使用 pbc-lua 原生 proto2 解码），CP 收到的是 JSON，不存在版本兼容问题。