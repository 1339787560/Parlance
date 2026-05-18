---
name: dailylottery-program-design
description: 对局抽奖模块程序设计文档 — 任务/奖励/配置/防刷/安全关闭五个子模块
---

# 对局抽奖模块 — 程序设计文档

> 模块名：dailylottery
> 角色：CP-DEV-xzmp
> 日期：2026-05-18

---

## 0. 模块总览

**模块职责**：玩家在普通房间完成对局 → 累计局数 → 完成阶段任务 → 自动获得抽奖券 → 使用抽奖券抽奖获取奖励。

**模块边界**：
- 输入：对局结算通知（GameSvr）、客户端请求（抽奖/查询）、定时器（重置）
- 输出：发奖（modsvr.async_batch_send_reward）、客户端通知、钉钉报警、邮件补发通知
- 依赖：configCenter 模块（配置版本管理）、账号系统（防刷，待确认）

**CONST_VAR**：

```typescript
const CONST_VAR = {
    MODULE_NAME: 'dailylottery',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
    TICKET_LIMIT: 999,            // 抽奖券虚拟计数上限
    RECORD_MAX_COUNT: 50,         // 获奖记录最大条数
    CONFIG_CENTER_MODULE: 'ConfigCenter',
}
```

**REQ_NAME**：

```typescript
const REQ_NAME = {
    // From Client
    QUERY_DAILYLOTTERY: 'queryDailyLottery',       // 查询抽奖界面数据
    DRAW_LOTTERY: 'drawLottery',                   // 抽奖
    QUERY_RECORDS: 'queryDailyLotteryRecords',     // 查获奖记录

    // From GameSvr
    ON_BOUT_FINISH: 'onBoutFinish',                // 对局结算

    // From/To Module
    FORCE_UPDATE_CONFIG: 'forceUpdateDailyLotteryConfig',
    GET_CONFIG_VERSION: 'getConfigVersion',         // 向 ConfigCenter 查旧配置

    // To Client (notify)
    NOTIFY_TICKET_GAINED: 'notifyTicketGained',    // 自动获得抽奖券
    NOTIFY_DRAW_RESULT: 'notifyDrawResult',         // 抽奖结果
}
```

---

## 1. 任务模块

### 1.1 数据模型

**MySQL 单表约束**：

```sql
CREATE TABLE tblcpuserdata_dailylottery_xzmp (
    userid  BIGINT,
    name    VARCHAR(64),    -- "DailyLotteryInfo"
    data    TEXT,           -- JSON
    PRIMARY KEY (userid, name)
);
```

每用户 **1 行**，`name = "DailyLotteryInfo"`，`data` 存全量 JSON（符合现有模块惯例：每模块每用户1行1个name值）。

**数据结构定义**：

```typescript
interface DailyLotteryData {
    // 全局状态
    lastResetDate: string;      // 上次每日重置日期 "YYYY-MM-DD"
    lastWeeklyDate: string;     // 上次每周重置日期 "YYYY-MM-DD"
    failedRewards: FailedReward[]; // 发奖失败记录
    records: RecordItem[];      // 获奖记录（最多50条）

    // 5场次进度（Map: roomCode → 进度数据）
    rooms: {
        [key: string]: RoomPlayerData;  // key = "R1"~"R5"
    };
}

interface RoomPlayerData {
    stageCode: string;       // 当前阶段标识 A/B/C/D
    curWins: number;         // 当前阶段已完成局数
    ticketCount: number;     // 抽奖券虚拟计数余额
    drawCount: number;       // 今日已抽奖次数
    configVer: string;       // 任务生成时绑定的配置版本号 (YYYYMMDDHHmmss)
    newbieDone: number;      // 新手任务是否已完成 0/1
}

interface FailedReward {
    propid: number;
    count: number;
    ts: number;             // 失败时间戳
    roomCode: string;       // 对应场次
    poolId: string;         // 对应奖池ID
}

interface RecordItem {
    propid: number;
    count: number;
    ts: number;             // 获奖时间戳
    roomCode: string;       // 对应场次
}
```

**Redis 缓存**：

```
Key: mod(cp):name(dailylottery):appcode(xzmp):uid({uid}):DailyLotteryInfo
Value: JSON (DailyLotteryData)
EXPIRE: 7天

Key: mod(cp):name(dailylottery):appcode(xzmp):uid({uid}):lock
Value: 分布式锁 (抽奖并发保护)
EXPIRE: 5秒
```

符合现有模块惯例：每模块每用户1个FUNC_INFO（`DailyLotteryInfo`）。获奖记录、失败记录、场次进度全部打包在同一 JSON 中，读写时整体序列化。

### 1.2 任务生成

**触发时机**：对局结算回调（OnGameResult / OnInternalCall from GameSvr）

**流程**：

```
1. 收到对局结算通知，携带 {userid, roomCode, boutResult}
2. 检查 isenable → 若为0则忽略
3. 检查 continueCount → 若为0则忽略（暂停计数）
4. 检查 rooms[roomCode].roomSwitch → 若为0则忽略
5. 检查今日是否已重置 → 未重置则先执行每日重置
6. 查用户数据 data（Redis→MySQL双写），取 roomData = data.rooms[roomCode]
7. 若 roomData.configVer 为空 → 绑定当前最新配置版本号（向 ConfigCenter 查询）
8. 从 ConfigCenter 获取该 configVer 对应的配置
9. roomData.curWins += 1
10. 查当前阶段的 targetWins → 判断 curWins >= targetWins
11. 若达标：
    a. roomData.ticketCount += ticketPerComplete（受 TICKET_LIMIT 上限限制）
    b. 通知客户端 NOTIFY_TICKET_GAINED
    c. 计算溢出局数：overflowWins = roomData.curWins - targetWins
    d. 阶段推进：查下一阶段 → 若是末段则不推进（循环）
    e. roomData.curWins = overflowWins（带入下一阶段）
12. 写回用户数据（MySQL + Redis 双写）
```

**新手任务**：

- 新手任务在 DL_Rx 中用 `newbieDone` 标记
- `newbieDone == 0` 时，首次对局结算走新手任务配置（`newbieTask`），完成后 `newbieDone = 1`
- 新手任务不做完不重置，最多保留90天（DL_GLOBAL 中可记录新手任务开始时间）
- 新手任务完成后，自动衔接该场次正常阶段 A

### 1.3 重置逻辑

**每日重置（0:00）**：

```
OnDistributedTimer → 每日0点触发
1. 就地重置（用户下次访问时检查 lastResetDate != today）：
   - 遍历 data.rooms 中每个 roomData：
     - roomData.curWins = 0
     - roomData.stageCode = "A"（回到首阶段）
     - roomData.drawCount = 0
     - roomData.configVer = ""（清空，下次生成任务时绑定最新版本）
   - data.lastResetDate = today
2. 写回用户数据
```

实际实现不遍历所有用户，而是在用户下次访问时检查 `lastResetDate != today` → 就地重置。

**每周重置（周一 0:00）**：

```
OnDistributedTimer → 每周一0点触发（与每日重置合并执行）
1. 就地重置（用户下次访问时检查 lastWeeklyDate != 本周一）：
   - 遍历 data.rooms 中每个 roomData：
     - roomData.ticketCount = 0
   - data.lastWeeklyDate = today
2. 写回用户数据
```

同样采用懒重置：用户下次访问时检查 `lastWeeklyDate != 本周一` → 就地清零券。

---

## 2. 奖励模块

### 2.1 抽奖券

抽奖券为**虚拟计数**，不发真实道具到背包。仅在 `ticketCount` 字段中维护。

**获取**：对局结算自动加，不做手动领取。
**消耗**：抽奖时扣 1，`drawCount += 1`。
**上限**：`ticketCount <= TICKET_LIMIT(999)`，到上限后对局结算不再加券，提示"抽奖券已达上限"。
**每周清零**：周一 0:00 `ticketCount = 0`。

### 2.2 抽奖流程

```
客户端请求 DRAW_LOTTERY {roomCode}
1. 检查 isenable → 关闭则返回 E_MODULE_DISABLED + 最新配置
2. 检查 roomSwitch → 关闭则返回 E_ROOM_DISABLED + 最新配置
3. 加分布式锁（redis lockKey, TTL=5s）
4. 查用户数据，取 roomData = data.rooms[roomCode]
5. roomData.ticketCount <= 0 → 返回错误 + toast文案
6. roomData.drawCount >= maxDrawCount → 返回错误 "今日抽奖次数已达上限"
7. roomData.ticketCount -= 1, roomData.drawCount += 1
8. 获取当前阶段 configVer 对应的配置
9. 查当前 stageCode 绑定的 rewardPoolId
10. 权重累加随机算法：从 slots 中抽出一个奖励
11. 构造 reward {propid, count, guid} → async_batch_send_reward
12. 若发奖成功：
    - 记录获奖记录（append 到 data.records，超50条 pop 旧记录）
    - 通知客户端 NOTIFY_DRAW_RESULT
    - 写回用户数据
13. 若发奖失败：
    - 记录到 data.failedRewards
    - 发钉钉报警日志（包含 guid、poolId、propid、count、错误信息）
    - 写回用户数据（扣券不回滚，券已消耗是事实）
14. 释放分布式锁
```

**权重累加随机算法**（参考 luckyturntable）：

```
1. 遍历 slots，计算 totalWeight = sum(slots[i].p)
2. 生成 random = Math.random() * totalWeight
3. 遍历 slots，累加权重，当累加值 >= random 时命中该 slot
```

### 2.3 发奖失败恢复

**记录格式**：

```typescript
interface FailedReward {
    propid: number;
    count: number;
    ts: number;
    roomCode: string;
    poolId: string;
}
```

**恢复时机**：每次玩家登录（`OnLogon`）

```
1. 查用户数据 data.failedRewards
2. 若为空 → 跳过
3. 遍历每条失败记录：
   a. 尝试 async_batch_send_reward({propid, count, guid})
   b. 成功 → 从 data.failedRewards 删除该条 → 发邮件告知补发成功
   c. 失败 → 保留，下次登录再试
4. 写回用户数据
```

**钉钉报警格式**：

```
[对局抽奖-发奖失败]
uid: {uid}
场次: {roomCode}
奖池: {poolId}
道具: propid={propid} count={count}
时间: {ts}
guid可用性: 需关注
```

---

## 3. 配置系统

### 3.1 ConfigCenter 模块（独立模块）

`ConfigCenter` 是独立模块，为多个模块提供配置版本管理服务。

**核心接口**（通过 `async_internal_call` 调用）：

```typescript
// 注册配置：模块配置变更时调用
REQ: "registerConfig"
DATA: {moduleName, configVer, configData}
→ ConfigCenter 存储一份配置快照，key = moduleName + configVer

// 查询配置：需要旧版本配置时调用
REQ: "getConfigByVersion"
DATA: {moduleName, configVer}
→ 返回对应版本的配置数据

// 查询最新配置版本号
REQ: "getCurrentConfigVer"
DATA: {moduleName}
→ 返回当前最新版本号 (YYYYMMDDHHmmss)

// 设置过期时间
REQ: "setConfigExpire"
DATA: {moduleName, retainDays}
→ 超过 retainDays 的旧版本配置自动清理
```

**数据存储**：

- 内存：`Map<moduleName, Map<configVer, configData>>` — 热数据
- Redis：`mod(cp):name(ConfigCenter):appcode(xzmp):cfg({moduleName}):ver({configVer})` — 持久化备份
- 保留最近 7 天配置版本，更早的自动清理

### 3.2 dailylottery 与 ConfigCenter 的交互

```
dailylottery 侧：
  OnScriptReload →
    1. parse_config 获取新配置
    2. configVer = formatDate(new Date(), 'YYYYMMDDHHmmss')
    3. async_internal_call → ConfigCenter.registerConfig({moduleName, configVer, configData})
    4. currentConfigVer = configVer

  任务生成时（configVer 为空）→
    1. 直接使用内存中的当前配置
    2. configVer = currentConfigVer
    3. 写入 DL_Rx.configVer

  已有任务需要旧配置 →
    1. async_internal_call → ConfigCenter.getConfigByVersion({moduleName, DL_Rx.configVer})
    2. 用返回的旧配置执行逻辑

ConfigCenter 侧：
  配置过期清理 → OnDistributedTimer 每日检查，删除超过7天的版本快照
```

### 3.3 版本降级

若玩家的 `configVer` 指向已被清理的旧版本：

```
1. ConfigCenter 返回空（版本已过期）
2. dailylottery 降级使用 currentConfigVer
3. 记录告警日志：uid={uid}, oldVer={expiredVer}, downgrade to {currentConfigVer}
4. 更新 DL_Rx.configVer = currentConfigVer
```

---

## 4. 防刷机制

> **状态：悬而未决。需与中台确认具体防刷思路后再定方案。以下仅提供设计思路供讨论。**

### 4.1 威胁分析

核心威胁：批量注册新账号 → 打1局完成新手任务（门槛极低）→ 获得银子奖励 → 转走银子到主号。

新手任务的低门槛特性（1局完成）使其成为刷子的首选目标。

### 4.2 思路A：hardid 设备维度限额

```
Redis:
  Hash: dailylottery:hardid:{hardid}
    dailyNewbieCompleteCount  INT  -- 该设备今日完成新手任务次数
    dailyNewbieCompleteLimit  INT  -- 上限（配置值，如3）

触发：新手任务完成时 hardid 维度检查
超限：该 hardid 下所有账号新手任务不再发券，但仍允许正常任务流程
```

- 优点：直接限制单设备批量注册
- 缺点：hardid 可篡改/刷机，模拟器可伪造不同 hardid

### 4.3 思路B：IP 维度限额

```
Redis:
  Hash: dailylottery:ip:{ip}
    dailyNewbieCompleteCount  INT
    dailyNewbieCompleteLimit  INT

触发：新手任务完成时 IP 维度检查
```

- 优点：覆盖模拟器集群（同一出口IP）
- 缺点：NAT 共享 IP 误伤正常用户（公司/校园网）

### 4.4 思路C：手机号维度限额（需中台账号系统配合）

```
触发：新手任务完成时 → async_internal_call 账号系统 → 查该手机号下所有账号今日完成数
超限：该手机号下所有账号新手任务不再发券
```

- 优点：识别力最强（实名绑定）
- 缺点：需跨模块调用账号系统增加延迟；手机号隐私合规风险

### 4.5 思路D：延迟发奖 + 行为验证

```
新手任务奖励不立即发放，延迟 24-72 小时：
- 延迟期内观察账号行为（是否继续打牌、是否异常转账）
- 正常玩家继续打牌 → 到期正常发奖
- 批量注册号只打1局不活跃 → 延迟期不发奖
- 可配合账号系统标记异常账号
```

- 优点：不误伤正常用户，行为驱动判断
- 缺点：延迟发放影响新手正反馈体验；需与中台协作判定活跃度

### 4.6 思路E：限制银子转移通道（不在本模块）

```
不在本模块防刷，而是在银子转移场景限制：
- 注册 < 7天 或 对局 < 10局 → 不可转出银子
- 从根源堵住银子汇聚
```

- 优点：从根源堵住，本模块无需改动
- 缺点：不在本模块控制范围，需中台/游戏服务配合

### 4.7 建议

**待中台确认后再选定方案。** 推荐优先探讨思路E（根源堵截），若中台不支持则降级到思路A+B组合（hardid+IP双维度限额）。思路D可作为辅助手段叠加使用。

---

## 5. 安全关闭机制

### 5.1 三级开关

| 层级 | 字段 | 位置 | 语义 | 效果 |
|---|---|---|---|---|
| 模块级 | `isenable` | 配置顶层 | 模块总开关 | 0=整个模块关闭，所有请求返回错误；1=开启 |
| 计数暂停 | `continueCount` | 配置顶层 | 暂停对局计数 | 0=暂停对局计数和发券（已有券仍可抽奖）；1=正常计数和发券 |
| 场次级 | `roomSwitch` | rooms[i] | 单场次开关 | 0=该场次暂停计数和发券；1=正常 |

**三者的关系**：
- `isenable=0` 时无论 `continueCount` 和 `roomSwitch` 取何值，整个模块都不工作
- `isenable=1 && continueCount=0` 时：对局不计入进度、不发券，但抽奖请求仍可正常处理（消耗已有券）。**同时自动开启定时器**，在下一个抽奖券重置时间（周一 0:00）将内存中 `isenable` 自动设为 0，实现渐进关闭
- `isenable=1 && continueCount=1 && roomSwitch=0` 时：仅该场次暂停计数，其他场次正常，该场次抽奖仍可用已有券

### 5.2 渐进关闭机制（continueCount=0 → 定时器 → isenable=0）

运营设 `continueCount=0` 表示"准备关闭模块，给玩家宽限期消耗剩余券"。

**流程**：

```
OnScriptReload → 检测到 continueCount 从 1 变为 0：
1. 停止对局计数和发券（continueCount=0 生效）
2. 计算下一个抽奖券重置时间：
   - 当前时间距本周一 0:00 的剩余秒数
   - 若已过本周一，则取下周一 0:00
3. 注册 OnDistributedTimer 定时器，触发时间 = 下周一 0:00
4. 定时器触发时：
   - 内存中 isenable 自动设为 0
   - internal_broadcast 通知所有模块线程
   - 记录日志：[对局抽奖] continueCount=0 定时器触发，isenable 自动关闭
```

**效果**：
- `continueCount=0` 到周一 0:00 之间：玩家仍可消耗已有券抽奖（宽限期）
- 周一 0:00 之后：`isenable=0`，所有请求拒绝，模块彻底关闭
- 周一 0:00 同时也是抽奖券清零时间，宽限期结束时券自然清零，无浪费

**恢复**：运营重新设 `continueCount=1` 时，取消定时器，恢复正常计数。若 `isenable` 已被定时器自动关闭，需同时设 `isenable=1` 才能恢复。

### 5.3 关闭后的行为

**isenable = 0**：
- 所有请求 → 返回 `E_MODULE_DISABLED` + 最新配置信息
- 客户端据此隐藏整个入口

**continueCount = 0**：
- 对局结算 → 不计入进度，不发券
- 抽奖请求 → 正常处理（消耗已有券，正常发奖）
- 查询请求 → 正常返回，进度冻结不变
- 效果：临时暂停"打牌得券"通道，但不回收已有券

**roomSwitch = 0**：
- 该场次对局结算 → 不计入进度，不发券
- 该场次抽奖请求 → 正常处理（已有券仍可抽奖）
- 其他场次 → 正常运行
- 客户端不展示该场次 tab

### 5.4 配置变更通知

```
OnScriptReload →
  1. loadConfig(true)
  2. 比较 isenable / continueCount / roomSwitch 是否有变化
  3. 若有变化 → internal_broadcast 通知所有模块线程刷新内存开关状态
```

客户端不需要主动推送，下次请求时自然感知变化。

### 5.5 错误码设计

```typescript
enum E_DailyLottery_Error {
    SUCCESS = 0,
    E_MODULE_DISABLED = 1001,    // 模块已关闭 (isenable=0)
    E_COUNT_PAUSED = 1002,       // 计数暂停 (continueCount=0)，不影响抽奖
    E_ROOM_DISABLED = 1003,      // 该场次已关闭 (roomSwitch=0)，不影响抽奖
    E_NO_TICKET = 1004,          // 抽奖券余额不足
    E_DRAW_LIMIT = 1005,         // 今日抽奖次数已达上限
    E_TICKET_LIMIT = 1006,       // 抽奖券已达上限
    E_DRAW_IN_PROGRESS = 1007,   // 正在抽奖中
    E_BOUT_NOT_COUNTED = 1008,   // 该对局不计入进度（比赛场等）
    E_CONFIG_ERROR = 1009,       // 配置异常
}
```

### 5.6 响应格式

所有错误响应统一携带最新配置信息，便于客户端更新界面：

```typescript
interface ErrorResponse {
    error: number;            // E_DailyLottery_Error
    errorMsg: string;         // 描述文案
    latestConfig: {
        isenable: number;
        rooms: {roomCode: string, roomSwitch: number, gameTypes: string[]}[];
    };
}
```

---

## 6. 模块间交互总图

```
┌─────────────┐     OnGameResult      ┌──────────────────┐
│   GameSvr   │ ─────────────────────→ │  dailylottery    │
└─────────────┘                        │                  │
                                       │  OnClientRequest │←── Client (query/draw)
┌─────────────┐  async_internal_call   │  OnInternalCall  │←── ConfigCenter
│configCenter │ ←────────────────────→ │  OnLogon         │   (补发/防刷检查)
└─────────────┘                        │  OnDistributed   │←── Timer (重置)
                                       │                  │
                                       │  async_batch_    │→ modsvr (发奖)
                                       │  send_reward     │
                                       │                  │
                                       │  send_log        │→ 钉钉报警
                                       │  async_send_mail │→ 邮件补发通知
                                       └──────────────────┘
```

---

## 7. MySQL / Redis 一览

**MySQL 单表**：`tblcpuserdata_dailylottery_xzmp`
- 每用户 1 行，`name = "DailyLotteryInfo"`
- data 字段 JSON 存储全量数据（5场次进度 + 全局状态 + 获奖记录 + 失败记录）

**Redis Keys**：

| Key | 类型 | EXPIRE | 说明 |
|---|---|---|---|
| `mod(cp):name(dailylottery):appcode(xzmp):uid({uid}):DailyLotteryInfo` | String(JSON) | 7天 | 全量用户数据 |
| `mod(cp):name(dailylottery):appcode(xzmp):uid({uid}):lock` | String | 5秒 | 分布式锁 |

---

## 8. 待确认事项

| 项 | 状态 | 说明 |
|---|---|---|
| 防刷方案 | 待中台确认 | 4.2~4.6五种思路，需与中台讨论后选定 |
| 钉钉报警接入 | 待确认 | 报警格式和Webhook地址需运维提供 |
| guid 可用性监控 | 待确认 | 是否有现有监控机制，还是需新建 |
| ConfigCenter 模块 | 待实现 | 需先开发 ConfigCenter 再开发 dailylottery |
| ticketPropId | 待确认 | 配置中 99999 为占位值，需道具系统确认 |
| guid | 待确认 | 配置中为占位值，需兑换系统分配 |
| 对局结算通知格式 | 待与GameSvr确认 | 消息名、携带字段(roomCode/boutResult等) |