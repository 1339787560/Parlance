# CP-DEV Doc System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the CP-DEV documentation system — merge role description, add common interface reference, add module index, rewrite impl docs as L3 module details.

**Architecture:** Purely documentation changes. No code. Files are created/modified/deleted in the CP-DEV directory. L3 docs follow a strict template for format consistency.

**Tech Stack:** Markdown documentation only.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `CP-DEV/L0_Index.md` | Modify | Merge CP-DEV.md content, update doc index table |
| `CP-DEV/CP-DEV.md` | Delete | Redundant after merge into L0_Index |
| `CP-DEV/L1_CommonInterface.md` | Create | Public interface quick-reference (6 sections) |
| `CP-DEV/L2_ModuleIndex.md` | Create | Module overview index with one-line summaries |
| `CP-DEV/L3_cmquickrecharge_xzmp.md` | Create | Rewritten from impl + code reference |
| `CP-DEV/L3_cmnewplayerdailygift_xzmp.md` | Create | Rewritten from impl + code reference |
| `CP-DEV/doc/cmquickrecharge_xzmp_impl.md` | Delete | Replaced by L3 |
| `CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md` | Delete | Replaced by L3 |

---

### Task 1: Merge CP-DEV.md into L0_Index.md

**Files:**
- Modify: `CP-DEV/L0_Index.md`
- Delete: `CP-DEV/CP-DEV.md`

- [ ] **Step 1: Add merged content to L0_Index.md**

Add the following after the `# L0 全局索引 - CPDev` heading line (before `## 核心职责`):

```markdown
> 角色名称: CP-DEV（游戏礼包服务工程师）
> 技能标签: TypeScript, CP服务, 协程服务器, 协议处理, 业务逻辑
```

Add the following as a new section after `## 服务实现细节` and before `## 文档索引`:

```markdown
---

## 注意事项

1. ts 脚本在 C++ 协程服务器中执行
2. 仅能通过 HTTP 接口阅览 A2AFile 下的内容
```

- [ ] **Step 2: Update the doc index table in L0_Index.md**

Replace the current `## 文档索引` table with:

```markdown
## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 公共接口 | [L1_CommonInterface.md](L1_CommonInterface.md) | 发奖、通知、数据库等公共接口快速参考 |
| 模块索引 | [L2_ModuleIndex.md](L2_ModuleIndex.md) | 所有模块总览索引 |
| 设计模式 | [L2_DesignPatterns.md](L2_DesignPatterns.md) | cpscript 设计模式、数据存储规范、模块通信 |
| 项目上下文 | [L2_Context.md](L2_Context.md) | cpscript 目录结构、开发规范 |
| 补充金币-原型 | [doc/cmquickrecharge_xzmp_proto.md](doc/cmquickrecharge_xzmp_proto.md) | 补充金币模块需求原型 |
| 补充金币-详情 | [L3_cmquickrecharge_xzmp.md](L3_cmquickrecharge_xzmp.md) | 补充金币模块详情 |
| 迎新礼包-原型 | [doc/cmnewplayerdailygift_xzmp_proto.md](doc/cmnewplayerdailygift_xzmp_proto.md) | 迎新礼包模块需求原型 |
| 迎新礼包-详情 | [L3_cmnewplayerdailygift_xzmp.md](L3_cmnewplayerdailygift_xzmp.md) | 迎新礼包模块详情 |
```

- [ ] **Step 3: Delete CP-DEV.md**

Run: `rm CP-DEV/CP-DEV.md`

- [ ] **Step 4: Commit**

```bash
git add CP-DEV/L0_Index.md
git rm CP-DEV/CP-DEV.md
git commit -m "Merge CP-DEV.md into L0_Index, delete redundant role description"
```

---

### Task 2: Create L1_CommonInterface.md

**Files:**
- Create: `CP-DEV/L1_CommonInterface.md`

- [ ] **Step 1: Write L1_CommonInterface.md**

Create the file with this content (extracted from L2_DesignPatterns.md — interface signatures and call patterns only, no implementation details):

```markdown
# L1 公共接口参考

> 快速参考：我要做 X，该调什么、怎么调。

---

## 1. 发奖接口

### 标准发奖

```typescript
// 单次发奖
await modsvr.async_batch_send_reward(src, cxt, userid, rewardList, guid);
```

- `rewardList`: `Array<{ propid: number, count: number }>`
- `guid`: 发奖唯一标识（来自配置的 `guid` 字段），用于防重复发放

### 大额金币分批发奖

```typescript
// 超过 20 亿金币时必须分批
await modsvr.async_sendGoldCoin_super(src, cxt, userid, totalAmount, guid);
```

---

## 2. 通知客户端

### 推送消息

```typescript
CommonFuncs.notifyClient(src, cxt, userid, msgName, data);
```

- `msgName`: 消息名（对应客户端监听的事件名）
- `data`: 任意对象，会 JSON.stringify 后发送
- 底层使用 `modsvr.PB_CP__CLIENT_NOTIFY` 协议号
- 终端: `modsvr.E_NOTIFY_TERMINAL.CLIENT`

### 消息格式

```typescript
// 推送数据格式（客户端收到的）
{
    req: msgName,       // 消息名
    data: { ... }       // 业务数据
}
```

---

## 3. 通知其他模块

### 内部模块调用

```typescript
let src = { client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid: 0 }, mods: [] };
await CommonFuncs.async_internal_call(src, cxt, REQ_NAME.XXX, targetModuleName, data);
```

- `targetModuleName`: 目标模块的 MODULE_NAME
- `data`: 传给目标模块 OnInternalCall 的业务数据

### 请求格式（目标模块收到的）

```typescript
{
    req: "消息名",
    modulename: "调用方模块名",
    data: { /* 业务数据 */ }
}
```

### 响应格式（目标模块返回的）

```typescript
iresp.resp = { id: 0, data: {} };
```

- `id`: 0 表示失败，1 表示成功

---

## 4. 配置读取

### 加载配置

```typescript
// 首次加载
let config = CommonFuncs.loadConfig();

// 强制刷新（如 OnScriptReload 时）
let config = CommonFuncs.loadConfig(true);
```

- 配置文件名格式：`{MODULE_NAME}_{APP_CODE}`，后缀 `.jsonc`
- 内部使用 `modsvr.parse_config` 解析
- 全局缓存：首次加载后缓存在 `CommonFuncs.g_config`，`bForce=true` 时重新解析

---

## 5. 数据库操作

### MySQL 查询

```typescript
let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
let res = await mysqlTool.async_query();
```

- 返回空时：`isEmpty_DBRes(res)` 返回 `true`
- 表名格式：`tblcpuserdata_{MODULE_NAME}_{GAME_CODE}`
- 每行数据：`userid` + `name` 字段定位，`data` 字段存 JSON

### MySQL 写入

```typescript
await mysqlTool.async_safeSave(data);
```

- 内部：先 query 判断是否存在 → INSERT 或 UPDATE
- 使用 `mysql.escape()` 防止 SQL 注入

### Redis 读取

```typescript
let redisTool = new RedisTool_XxxInfo(cxt, userid);
let res = await redisTool.async_getData();
```

### Redis 写入

```typescript
await redisTool.async_setData(data);
```

- 自动设置过期时间（默认 7 天）
- Key 格式：`mod(cp):name({MODULE_NAME}):appcode({APP_CODE}):uid({uid}):{FUNC_INFO}`

### 双写模式（标准查询/写入）

```typescript
// 查询：Redis 优先，miss 则查 MySQL 并回写 Redis
async function async_QueryXxxInfo(cxt, userid) {
    let redisTool = new RedisTool_XxxInfo(cxt, userid);
    let res = await redisTool.async_getData();
    if (!isEmpty_DBRes(res)) return res;

    let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
    res = await mysqlTool.async_query();
    if (isEmpty_DBRes(res)) {
        res = new DefaultData();
        await mysqlTool.async_safeSave(res);
    }
    await redisTool.async_setData(res);
    return res;
}

// 写入：MySQL + Redis 双写
async function async_WriteXxxInfo(cxt, userid, data) {
    let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
    await mysqlTool.async_safeSave(data);
    let redisTool = new RedisTool_XxxInfo(cxt, userid);
    await redisTool.async_setData(data);
}
```

---

## 6. 分布式锁

```typescript
let redisTool = new RedisTool_XxxInfo(cxt, userid);
await redisTool.async_redis_lock_key(redisTool.lockKey, async () => {
    // 临界区逻辑
}, ttl);
```

- 底层：SET NX PX 原子加锁
- 失败重试：间隔 50/100/300/500/1000ms
- `ttl`: 可选，默认使用 MAX_REDIS_EXPIRE
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L1_CommonInterface.md
git commit -m "Add L1_CommonInterface: public API quick reference for CP scripts"
```

---

### Task 3: Create L2_ModuleIndex.md

**Files:**
- Create: `CP-DEV/L2_ModuleIndex.md`

- [ ] **Step 1: Write L2_ModuleIndex.md**

```markdown
# L2 模块索引

> 四川麻将（xzmp）CP 服务脚本模块总览。

---

## 模块总览表

| 模块名 | 功能 | 脚本文件 | L3 详情 |
|--------|------|----------|---------|
| cmquickrecharge | 补充金币 | cmquickrecharge_xzmp.ts | [L3_cmquickrecharge_xzmp.md](L3_cmquickrecharge_xzmp.md) |
| cmnewplayerdailygift | 迎新礼包 | cmnewplayerdailygift_xzmp.ts | [L3_cmnewplayerdailygift_xzmp.md](L3_cmnewplayerdailygift_xzmp.md) |
| leveldefine | 等级系统 | leveldefine_xzmp.ts | — |
| cmmonthcard | 月卡 | cmmonthcard_xzmp.ts | — |
| cmdecoration | 装饰 | cmdecoration_xzmp.ts | — |

---

## 模块分类

### 充值/购买类
- **cmquickrecharge** — 补充金币，玩家金币不足时展示可购买礼包
- **cmmonthcard** — 月卡，周期性充值奖励
- **cmnewplayerdailygift** — 迎新礼包，新手充值后连续7天领取奖励

### 功能系统类
- **leveldefine** — 等级系统，经验值与等级管理
- **cmdecoration** — 装饰，桌布/头像框/聊天气泡等装扮管理
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L2_ModuleIndex.md
git commit -m "Add L2_ModuleIndex: module overview for xzmp CP scripts"
```

---

### Task 4: Create L3_cmquickrecharge_xzmp.md

**Files:**
- Create: `CP-DEV/L3_cmquickrecharge_xzmp.md`

This rewrites `doc/cmquickrecharge_xzmp_impl.md` into the strict L3 template format, referencing the actual code for accuracy.

- [ ] **Step 1: Write L3_cmquickrecharge_xzmp.md**

```markdown
# cmquickrecharge 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmquickrecharge |
| 脚本文件 | cmquickrecharge_xzmp.ts |
| 配置文件 | cmquickrecharge_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

当玩家金币不足时（点击房间入口或本局游戏结束时），弹出补足金币界面，展示两种可购买礼包。每个礼包携带一个特惠礼包，仅当玩家在指定天数内充值金额达到阈值时激活。特惠礼包一经激活永久有效，但每个组合仅能购买一次。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryCMQuickRechargeConfig | 查询补足金币配置及玩家状态 | 无 | `{ cfg, playerInfo }` |
| buySpecialGift | 购买特惠礼包校验（仅校验，不执行购买） | `{ gametype, roomlevel, giftlevel }` | `{ result }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| playerInfoChange_cmquickrecharge_xzmp | 玩家补足金币信息变化通知 | `{ playerInfo }` |

### 内部模块调用

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| onSpecialGiftPurchaseSuccess | 特惠礼包购买成功回调（支付成功后调用） | `{ gametype, roomlevel, giftlevel }` | `{ id, data: { success } }` |

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置并执行缺省填充（渠道→玩法层级填充） |
| OnPayResult | 更新充值流水，检查特惠激活条件，推送状态变化 |

## 数据结构

### GameConfig（配置）

```typescript
interface GameConfig {
    isenable: number;
    guid: string;
    RMB2TongbaoRatio: number;
    payconfig: PayConfig;
}

interface PayConfig {
    default: GameTypeConfig;
    gametype4?: GameTypeConfig;  // 血流六红中
    gametype5?: GameTypeConfig;  // 血流成河
    gametype6?: GameTypeConfig;  // 血战到底
}

interface GameTypeConfig {
    roomlevel1: RoomLevelConfig;
    roomlevel3: RoomLevelConfig;
    roomlevel4: RoomLevelConfig;
    roomlevel5: RoomLevelConfig;
}

interface RoomLevelConfig {
    levelNotShow: number;
    default: GiftLevelConfigs;
    wxan?: GiftLevelConfigs;
    wxios?: GiftLevelConfigs;
    tcyan?: GiftLevelConfigs;
    tcyios?: GiftLevelConfigs;
    mergean?: GiftLevelConfigs;
}

interface GiftLevelConfigs {
    giftlevel1: GiftConfig;
    giftlevel2: GiftConfig;
}

interface GiftConfig {
    price: number;
    propID: number;
    propcount: number;
    exchangeid: number;
    specialoffer: SpecialOffer;
}

interface SpecialOffer {
    price: number;
    propcount: number;
    exchangeid: number;
    chargedays: number;
    charge: number;
}
```

### QuickRechargeInfo（玩家数据）

```typescript
class QuickRechargeInfo {
    specialGiftStatus: { [key: number]: number };  // 特惠礼包状态
    payFlow: PayFlowItem[];                        // 充值流水（滑动窗口，保留90天）
}

class PayFlowItem {
    time: number;       // 时间戳（秒）
    amount: number;     // 充值金额（RMB分）
}
```

## 依赖模块

无（独立模块）

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| QUERY_CONFIG | queryCMQuickRechargeConfig | From Client |
| BUY_SPECIAL_GIFT | buySpecialGift | From Client |
| PLAYER_INFO_CHANGE | playerInfoChange_cmquickrecharge_xzmp | To Client |
| ON_SPECIAL_GIFT_PURCHASE_SUCCESS | onSpecialGiftPurchaseSuccess | From Module (Pay) |

## 特惠礼包 Key 编码

编码公式：`key = gametype * 100 + roomlevel * 10 + giftlevel`

| 状态值 | 常量 | 说明 |
|--------|------|------|
| 0 | NOT_PURCHASED | 未购买（未激活） |
| 1 | CAN_PURCHASE | 可购买（已激活） |
| 2 | PURCHASED | 已购买 |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | `tblcpuserdata_cmquickrecharge_xzmp`，name 字段: "QuickRechargeInfo" |
| Redis Key | `mod(cp):name(cmquickrecharge):appcode(xzmp):uid({uid}):QuickRechargeInfo`，过期: 7天 |

## 核心流程

### 充值回调 (OnPayResult)

1. 更新玩家充值流水（金额单位：RMB分）
2. 遍历所有玩法、房间等级、礼包等级组合
3. 获取渠道配置（优先渠道，无则用 default）
4. 检查是否满足特惠激活条件（`chargedays` 天内充值 >= `charge` 元）
5. 满足条件则激活对应 key 的特惠礼包
6. 推送玩家状态变化给客户端

### 购买特惠礼包流程

1. 客户端请求 `buySpecialGift` → CP 校验（仅校验，不更新状态）
2. 校验通过 → 客户端发起支付请求
3. 支付成功 → 支付模块调用 `onSpecialGiftPurchaseSuccess`
4. CP 更新购买状态为 PURCHASED

### 配置缺省填充 (OnScriptReload)

1. **内层填充**：对每个玩法，用房间等级下的 `default` 渠道配置填充缺省的渠道配置
2. **外层填充**：用 `default` 玩法配置填充缺省的 `gametype4/5/6`

## 错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 可以购买 |
| -1 | 模块未启用 |
| -2 | 礼包已购买 |
| -3 | 礼包未激活 |
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L3_cmquickrecharge_xzmp.md
git commit -m "Add L3_cmquickrecharge_xzmp: rewritten module detail from impl + code"
```

---

### Task 5: Create L3_cmnewplayerdailygift_xzmp.md

**Files:**
- Create: `CP-DEV/L3_cmnewplayerdailygift_xzmp.md`

This rewrites `doc/cmnewplayerdailygift_xzmp_impl.md` into the strict L3 template format.

- [ ] **Step 1: Write L3_cmnewplayerdailygift_xzmp.md**

```markdown
# cmnewplayerdailygift 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmnewplayerdailygift |
| 脚本文件 | cmnewplayerdailygift_xzmp.ts |
| 配置文件 | cmnewplayerdailygift_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

迎新礼包2 — 新手玩家充值后连续7天领取奖励。客户端判断玩家局数低于阈值时展示入口，玩家充值成功后立即发放第一天奖励，后续6天每日登录手动领取。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryNewPlayerDailyGiftConfig | 查询配置和玩家状态 | 无 | `{ cfg, giftInfo }` |
| claimDailyReward | 领取当日奖励 | 无 | `{ rewardDay, reward }` 或 `{ error }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| onNewPlayerDailyGiftPurchased | 充值成功，第一天奖励已发放 | `{ giftInfo, reward }` |

### 内部模块调用

无

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置 |
| OnPayResult | 判断 exchangeid 匹配后，发放第一天奖励，记录购买时间，推送通知客户端 |

## 数据结构

### NewPlayerDailyGiftConfig（配置）

```typescript
interface NewPlayerDailyGiftConfig {
    isenable: number;          // 开关，1启用，0禁用
    guid: string;              // 发奖唯一标识
    newuserbout: number;       // 新手判定局数上限
    limittime: number;         // 限时展示时间（秒），UI展示用
    checkindays: number;       // 签到总天数
    checkinPropID: number;     // 签到奖励道具ID（金币: 21770）
    checkinReward: number[];   // 7天奖励列表，索引0为第一天
    clientDesc: string;        // 客户端展示描述模板
    exchangeid: number;        // 充值商品ID
}
```

### UserData_NewPlayerDailyGiftInfo（玩家数据）

```typescript
class UserData_NewPlayerDailyGiftInfo {
    buyTime: number;           // 购买时间（秒级时间戳）
    lastClaimDay: number;      // 已领取到第几天 (0-6)
    lastClaimDate: number;     // 上次领取日期（YYYYMMDD）
}
```

### GiftInfo（推送给客户端的状态）

```typescript
interface GiftInfo {
    hasPurchased: boolean;
    buyTime: number;
    lastClaimDay: number;
    canClaimToday: boolean;
    remainingDays: number;
}
```

## 依赖模块

无（独立模块）

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| QUERY_CONFIG | queryNewPlayerDailyGiftConfig | From Client |
| CLAIM_DAILY_REWARD | claimDailyReward | From Client |
| ON_PURCHASED | onNewPlayerDailyGiftPurchased | To Client |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | `tblcpuserdata_cmnewplayerdailygift_xzmp`，name 字段: "NewPlayerDailyGiftInfo" |
| Redis Key | `mod(cp):name(cmnewplayerdailygift):appcode(xzmp):uid({uid}):NewPlayerDailyGiftInfo`，过期: 7天 |

## 核心流程

### 充值回调 (OnPayResult)

1. 判断 exchangeid 是否匹配配置的兑换商品
2. 检查是否已购买过（防止重复）
3. 发放第一天奖励（checkinReward[0]）
4. 记录购买时间和状态
5. 推送消息通知客户端

### 每日签到 (claimDailyReward)

1. 检查是否已购买
2. 检查今日是否已领取（比较 lastClaimDate）
3. 检查是否在有效期内（未超过 checkindays 天）
4. 发放当日奖励（checkinReward[lastClaimDay + 1]）
5. 更新 lastClaimDay 和 lastClaimDate

## 错误码

| 错误信息 | 说明 |
|---------|------|
| 礼包未启用 | 配置 isenable = 0 |
| 未购买礼包 | 玩家未购买迎新礼包 |
| 已领取完所有奖励 | 已领取全部7天奖励 |
| 今日已领取 | 当天已领取过 |
| 礼包已过期 | 超过 checkindays 天有效期 |
| 发放奖励失败 | 服务端发奖异常 |

## 常量定义

```typescript
const CONST_VAR = {
    MODULE_NAME: 'cmnewplayerdailygift',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}
```
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L3_cmnewplayerdailygift_xzmp.md
git commit -m "Add L3_cmnewplayerdailygift_xzmp: rewritten module detail from impl + code"
```

---

### Task 6: Delete impl documents

**Files:**
- Delete: `CP-DEV/doc/cmquickrecharge_xzmp_impl.md`
- Delete: `CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md`

- [ ] **Step 1: Delete both impl files**

```bash
rm CP-DEV/doc/cmquickrecharge_xzmp_impl.md
rm CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md
```

- [ ] **Step 2: Commit**

```bash
git add -u CP-DEV/doc/
git commit -m "Remove impl docs, replaced by L3 module details in CP-DEV root"
```
```

Now let me do the self-review.

**1. Spec coverage check:**
- Spec item 1 (merge CP-DEV.md → L0_Index): Task 1 ✓
- Spec item 2 (L1_CommonInterface.md): Task 2 ✓
- Spec item 3 (L2_ModuleIndex.md): Task 3 ✓
- Spec item 4 (L3 rewrites + delete impl): Tasks 4, 5, 6 ✓
- Spec item 5 (update L0_Index doc table): Task 1, Step 2 ✓

**2. Placeholder scan:** No TBD/TODO found. All code blocks contain actual content.

**3. Type consistency:** L3 template fields (基本信息, 功能概述, 主要函数, 数据结构, 依赖模块, 消息号列表) match across both L3 docs. No naming mismatches.

All good. Let me save.<tool_call>Write<arg_key>content</arg_key><arg_value># CP-DEV Doc System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the CP-DEV documentation system — merge role description, add common interface reference, add module index, rewrite impl docs as L3 module details.

**Architecture:** Purely documentation changes. No code. Files are created/modified/deleted in the CP-DEV directory. L3 docs follow a strict template for format consistency.

**Tech Stack:** Markdown documentation only.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `CP-DEV/L0_Index.md` | Modify | Merge CP-DEV.md content, update doc index table |
| `CP-DEV/CP-DEV.md` | Delete | Redundant after merge into L0_Index |
| `CP-DEV/L1_CommonInterface.md` | Create | Public interface quick-reference (6 sections) |
| `CP-DEV/L2_ModuleIndex.md` | Create | Module overview index with one-line summaries |
| `CP-DEV/L3_cmquickrecharge_xzmp.md` | Create | Rewritten from impl + code reference |
| `CP-DEV/L3_cmnewplayerdailygift_xzmp.md` | Create | Rewritten from impl + code reference |
| `CP-DEV/doc/cmquickrecharge_xzmp_impl.md` | Delete | Replaced by L3 |
| `CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md` | Delete | Replaced by L3 |

---

### Task 1: Merge CP-DEV.md into L0_Index.md

**Files:**
- Modify: `CP-DEV/L0_Index.md`
- Delete: `CP-DEV/CP-DEV.md`

- [ ] **Step 1: Add merged content to L0_Index.md**

Add the following after the `# L0 全局索引 - CPDev` heading line (before `## 核心职责`):

```markdown
> 角色名称: CP-DEV（游戏礼包服务工程师）
> 技能标签: TypeScript, CP服务, 协程服务器, 协议处理, 业务逻辑
```

Add the following as a new section after `## 服务实现细节` and before `## 文档索引`:

```markdown
---

## 注意事项

1. ts 脚本在 C++ 协程服务器中执行
2. 仅能通过 HTTP 接口阅览 A2AFile 下的内容
```

- [ ] **Step 2: Update the doc index table in L0_Index.md**

Replace the current `## 文档索引` table with:

```markdown
## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 公共接口 | [L1_CommonInterface.md](L1_CommonInterface.md) | 发奖、通知、数据库等公共接口快速参考 |
| 模块索引 | [L2_ModuleIndex.md](L2_ModuleIndex.md) | 所有模块总览索引 |
| 设计模式 | [L2_DesignPatterns.md](L2_DesignPatterns.md) | cpscript 设计模式、数据存储规范、模块通信 |
| 项目上下文 | [L2_Context.md](L2_Context.md) | cpscript 目录结构、开发规范 |
| 补充金币-原型 | [doc/cmquickrecharge_xzmp_proto.md](doc/cmquickrecharge_xzmp_proto.md) | 补充金币模块需求原型 |
| 补充金币-详情 | [L3_cmquickrecharge_xzmp.md](L3_cmquickrecharge_xzmp.md) | 补充金币模块详情 |
| 迎新礼包-原型 | [doc/cmnewplayerdailygift_xzmp_proto.md](doc/cmnewplayerdailygift_xzmp_proto.md) | 迎新礼包模块需求原型 |
| 迎新礼包-详情 | [L3_cmnewplayerdailygift_xzmp.md](L3_cmnewplayerdailygift_xzmp.md) | 迎新礼包模块详情 |
```

- [ ] **Step 3: Delete CP-DEV.md**

Run: `rm CP-DEV/CP-DEV.md`

- [ ] **Step 4: Commit**

```bash
git add CP-DEV/L0_Index.md
git rm CP-DEV/CP-DEV.md
git commit -m "Merge CP-DEV.md into L0_Index, delete redundant role description"
```

---

### Task 2: Create L1_CommonInterface.md

**Files:**
- Create: `CP-DEV/L1_CommonInterface.md`

- [ ] **Step 1: Write L1_CommonInterface.md**

Create the file with this content (extracted from L2_DesignPatterns.md — interface signatures and call patterns only, no implementation details):

```markdown
# L1 公共接口参考

> 快速参考：我要做 X，该调什么、怎么调。

---

## 1. 发奖接口

### 标准发奖

```typescript
// 单次发奖
await modsvr.async_batch_send_reward(src, cxt, userid, rewardList, guid);
```

- `rewardList`: `Array<{ propid: number, count: number }>`
- `guid`: 发奖唯一标识（来自配置的 `guid` 字段），用于防重复发放

### 大额金币分批发奖

```typescript
// 超过 20 亿金币时必须分批
await modsvr.async_sendGoldCoin_super(src, cxt, userid, totalAmount, guid);
```

---

## 2. 通知客户端

### 推送消息

```typescript
CommonFuncs.notifyClient(src, cxt, userid, msgName, data);
```

- `msgName`: 消息名（对应客户端监听的事件名）
- `data`: 任意对象，会 JSON.stringify 后发送
- 底层使用 `modsvr.PB_CP__CLIENT_NOTIFY` 协议号
- 终端: `modsvr.E_NOTIFY_TERMINAL.CLIENT`

### 消息格式

```typescript
// 推送数据格式（客户端收到的）
{
    req: msgName,       // 消息名
    data: { ... }       // 业务数据
}
```

---

## 3. 通知其他模块

### 内部模块调用

```typescript
let src = { client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid: 0 }, mods: [] };
await CommonFuncs.async_internal_call(src, cxt, REQ_NAME.XXX, targetModuleName, data);
```

- `targetModuleName`: 目标模块的 MODULE_NAME
- `data`: 传给目标模块 OnInternalCall 的业务数据

### 请求格式（目标模块收到的）

```typescript
{
    req: "消息名",
    modulename: "调用方模块名",
    data: { /* 业务数据 */ }
}
```

### 响应格式（目标模块返回的）

```typescript
iresp.resp = { id: 0, data: {} };
```

- `id`: 0 表示失败，1 表示成功

---

## 4. 配置读取

### 加载配置

```typescript
// 首次加载
let config = CommonFuncs.loadConfig();

// 强制刷新（如 OnScriptReload 时）
let config = CommonFuncs.loadConfig(true);
```

- 配置文件名格式：`{MODULE_NAME}_{APP_CODE}`，后缀 `.jsonc`
- 内部使用 `modsvr.parse_config` 解析
- 全局缓存：首次加载后缓存在 `CommonFuncs.g_config`，`bForce=true` 时重新解析

---

## 5. 数据库操作

### MySQL 查询

```typescript
let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
let res = await mysqlTool.async_query();
```

- 返回空时：`isEmpty_DBRes(res)` 返回 `true`
- 表名格式：`tblcpuserdata_{MODULE_NAME}_{GAME_CODE}`
- 每行数据：`userid` + `name` 字段定位，`data` 字段存 JSON

### MySQL 写入

```typescript
await mysqlTool.async_safeSave(data);
```

- 内部：先 query 判断是否存在 → INSERT 或 UPDATE
- 使用 `mysql.escape()` 防止 SQL 注入

### Redis 读取

```typescript
let redisTool = new RedisTool_XxxInfo(cxt, userid);
let res = await redisTool.async_getData();
```

### Redis 写入

```typescript
await redisTool.async_setData(data);
```

- 自动设置过期时间（默认 7 天）
- Key 格式：`mod(cp):name({MODULE_NAME}):appcode({APP_CODE}):uid({uid}):{FUNC_INFO}`

### 双写模式（标准查询/写入）

```typescript
// 查询：Redis 优先，miss 则查 MySQL 并回写 Redis
async function async_QueryXxxInfo(cxt, userid) {
    let redisTool = new RedisTool_XxxInfo(cxt, userid);
    let res = await redisTool.async_getData();
    if (!isEmpty_DBRes(res)) return res;

    let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
    res = await mysqlTool.async_query();
    if (isEmpty_DBRes(res)) {
        res = new DefaultData();
        await mysqlTool.async_safeSave(res);
    }
    await redisTool.async_setData(res);
    return res;
}

// 写入：MySQL + Redis 双写
async function async_WriteXxxInfo(cxt, userid, data) {
    let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
    await mysqlTool.async_safeSave(data);
    let redisTool = new RedisTool_XxxInfo(cxt, userid);
    await redisTool.async_setData(data);
}
```

---

## 6. 分布式锁

```typescript
let redisTool = new RedisTool_XxxInfo(cxt, userid);
await redisTool.async_redis_lock_key(redisTool.lockKey, async () => {
    // 临界区逻辑
}, ttl);
```

- 底层：SET NX PX 原子加锁
- 失败重试：间隔 50/100/300/500/1000ms
- `ttl`: 可选，默认使用 MAX_REDIS_EXPIRE
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L1_CommonInterface.md
git commit -m "Add L1_CommonInterface: public API quick reference for CP scripts"
```

---

### Task 3: Create L2_ModuleIndex.md

**Files:**
- Create: `CP-DEV/L2_ModuleIndex.md`

- [ ] **Step 1: Write L2_ModuleIndex.md**

```markdown
# L2 模块索引

> 四川麻将（xzmp）CP 服务脚本模块总览。

---

## 模块总览表

| 模块名 | 功能 | 脚本文件 | L3 详情 |
|--------|------|----------|---------|
| cmquickrecharge | 补充金币 | cmquickrecharge_xzmp.ts | [L3_cmquickrecharge_xzmp.md](L3_cmquickrecharge_xzmp.md) |
| cmnewplayerdailygift | 迎新礼包 | cmnewplayerdailygift_xzmp.ts | [L3_cmnewplayerdailygift_xzmp.md](L3_cmnewplayerdailygift_xzmp.md) |
| leveldefine | 等级系统 | leveldefine_xzmp.ts | — |
| cmmonthcard | 月卡 | cmmonthcard_xzmp.ts | — |
| cmdecoration | 装饰 | cmdecoration_xzmp.ts | — |

---

## 模块分类

### 充值/购买类
- **cmquickrecharge** — 补充金币，玩家金币不足时展示可购买礼包
- **cmmonthcard** — 月卡，周期性充值奖励
- **cmnewplayerdailygift** — 迎新礼包，新手充值后连续7天领取奖励

### 功能系统类
- **leveldefine** — 等级系统，经验值与等级管理
- **cmdecoration** — 装饰，桌布/头像框/聊天气泡等装扮管理
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L2_ModuleIndex.md
git commit -m "Add L2_ModuleIndex: module overview for xzmp CP scripts"
```

---

### Task 4: Create L3_cmquickrecharge_xzmp.md

**Files:**
- Create: `CP-DEV/L3_cmquickrecharge_xzmp.md`

This rewrites `doc/cmquickrecharge_xzmp_impl.md` into the strict L3 template format, referencing the actual code for accuracy.

- [ ] **Step 1: Write L3_cmquickrecharge_xzmp.md**

```markdown
# cmquickrecharge 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmquickrecharge |
| 脚本文件 | cmquickrecharge_xzmp.ts |
| 配置文件 | cmquickrecharge_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

当玩家金币不足时（点击房间入口或本局游戏结束时），弹出补足金币界面，展示两种可购买礼包。每个礼包携带一个特惠礼包，仅当玩家在指定天数内充值金额达到阈值时激活。特惠礼包一经激活永久有效，但每个组合仅能购买一次。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryCMQuickRechargeConfig | 查询补足金币配置及玩家状态 | 无 | `{ cfg, playerInfo }` |
| buySpecialGift | 购买特惠礼包校验（仅校验，不执行购买） | `{ gametype, roomlevel, giftlevel }` | `{ result }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| playerInfoChange_cmquickrecharge_xzmp | 玩家补足金币信息变化通知 | `{ playerInfo }` |

### 内部模块调用

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| onSpecialGiftPurchaseSuccess | 特惠礼包购买成功回调（支付成功后调用） | `{ gametype, roomlevel, giftlevel }` | `{ id, data: { success } }` |

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置并执行缺省填充（渠道→玩法层级填充） |
| OnPayResult | 更新充值流水，检查特惠激活条件，推送状态变化 |

## 数据结构

### GameConfig（配置）

```typescript
interface GameConfig {
    isenable: number;
    guid: string;
    RMB2TongbaoRatio: number;
    payconfig: PayConfig;
}

interface PayConfig {
    default: GameTypeConfig;
    gametype4?: GameTypeConfig;  // 血流六红中
    gametype5?: GameTypeConfig;  // 血流成河
    gametype6?: GameTypeConfig;  // 血战到底
}

interface GameTypeConfig {
    roomlevel1: RoomLevelConfig;
    roomlevel3: RoomLevelConfig;
    roomlevel4: RoomLevelConfig;
    roomlevel5: RoomLevelConfig;
}

interface RoomLevelConfig {
    levelNotShow: number;
    default: GiftLevelConfigs;
    wxan?: GiftLevelConfigs;
    wxios?: GiftLevelConfigs;
    tcyan?: GiftLevelConfigs;
    tcyios?: GiftLevelConfigs;
    mergean?: GiftLevelConfigs;
}

interface GiftLevelConfigs {
    giftlevel1: GiftConfig;
    giftlevel2: GiftConfig;
}

interface GiftConfig {
    price: number;
    propID: number;
    propcount: number;
    exchangeid: number;
    specialoffer: SpecialOffer;
}

interface SpecialOffer {
    price: number;
    propcount: number;
    exchangeid: number;
    chargedays: number;
    charge: number;
}
```

### QuickRechargeInfo（玩家数据）

```typescript
class QuickRechargeInfo {
    specialGiftStatus: { [key: number]: number };  // 特惠礼包状态
    payFlow: PayFlowItem[];                        // 充值流水（滑动窗口，保留90天）
}

class PayFlowItem {
    time: number;       // 时间戳（秒）
    amount: number;     // 充值金额（RMB分）
}
```

## 依赖模块

无（独立模块）

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| QUERY_CONFIG | queryCMQuickRechargeConfig | From Client |
| BUY_SPECIAL_GIFT | buySpecialGift | From Client |
| PLAYER_INFO_CHANGE | playerInfoChange_cmquickrecharge_xzmp | To Client |
| ON_SPECIAL_GIFT_PURCHASE_SUCCESS | onSpecialGiftPurchaseSuccess | From Module (Pay) |

## 特惠礼包 Key 编码

编码公式：`key = gametype * 100 + roomlevel * 10 + giftlevel`

| 状态值 | 常量 | 说明 |
|--------|------|------|
| 0 | NOT_PURCHASED | 未购买（未激活） |
| 1 | CAN_PURCHASE | 可购买（已激活） |
| 2 | PURCHASED | 已购买 |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | `tblcpuserdata_cmquickrecharge_xzmp`，name 字段: "QuickRechargeInfo" |
| Redis Key | `mod(cp):name(cmquickrecharge):appcode(xzmp):uid({uid}):QuickRechargeInfo`，过期: 7天 |

## 核心流程

### 充值回调 (OnPayResult)

1. 更新玩家充值流水（金额单位：RMB分）
2. 遍历所有玩法、房间等级、礼包等级组合
3. 获取渠道配置（优先渠道，无则用 default）
4. 检查是否满足特惠激活条件（`chargedays` 天内充值 >= `charge` 元）
5. 满足条件则激活对应 key 的特惠礼包
6. 推送玩家状态变化给客户端

### 购买特惠礼包流程

1. 客户端请求 `buySpecialGift` → CP 校验（仅校验，不更新状态）
2. 校验通过 → 客户端发起支付请求
3. 支付成功 → 支付模块调用 `onSpecialGiftPurchaseSuccess`
4. CP 更新购买状态为 PURCHASED

### 配置缺省填充 (OnScriptReload)

1. **内层填充**：对每个玩法，用房间等级下的 `default` 渠道配置填充缺省的渠道配置
2. **外层填充**：用 `default` 玩法配置填充缺省的 `gametype4/5/6`

## 错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 可以购买 |
| -1 | 模块未启用 |
| -2 | 礼包已购买 |
| -3 | 礼包未激活 |
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L3_cmquickrecharge_xzmp.md
git commit -m "Add L3_cmquickrecharge_xzmp: rewritten module detail from impl + code"
```

---

### Task 5: Create L3_cmnewplayerdailygift_xzmp.md

**Files:**
- Create: `CP-DEV/L3_cmnewplayerdailygift_xzmp.md`

This rewrites `doc/cmnewplayerdailygift_xzmp_impl.md` into the strict L3 template format.

- [ ] **Step 1: Write L3_cmnewplayerdailygift_xzmp.md**

```markdown
# cmnewplayerdailygift 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmnewplayerdailygift |
| 脚本文件 | cmnewplayerdailygift_xzmp.ts |
| 配置文件 | cmnewplayerdailygift_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

迎新礼包2 — 新手玩家充值后连续7天领取奖励。客户端判断玩家局数低于阈值时展示入口，玩家充值成功后立即发放第一天奖励，后续6天每日登录手动领取。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryNewPlayerDailyGiftConfig | 查询配置和玩家状态 | 无 | `{ cfg, giftInfo }` |
| claimDailyReward | 领取当日奖励 | 无 | `{ rewardDay, reward }` 或 `{ error }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| onNewPlayerDailyGiftPurchased | 充值成功，第一天奖励已发放 | `{ giftInfo, reward }` |

### 内部模块调用

无

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置 |
| OnPayResult | 判断 exchangeid 匹配后，发放第一天奖励，记录购买时间，推送通知客户端 |

## 数据结构

### NewPlayerDailyGiftConfig（配置）

```typescript
interface NewPlayerDailyGiftConfig {
    isenable: number;          // 开关，1启用，0禁用
    guid: string;              // 发奖唯一标识
    newuserbout: number;       // 新手判定局数上限
    limittime: number;         // 限时展示时间（秒），UI展示用
    checkindays: number;       // 签到总天数
    checkinPropID: number;     // 签到奖励道具ID（金币: 21770）
    checkinReward: number[];   // 7天奖励列表，索引0为第一天
    clientDesc: string;        // 客户端展示描述模板
    exchangeid: number;        // 充值商品ID
}
```

### UserData_NewPlayerDailyGiftInfo（玩家数据）

```typescript
class UserData_NewPlayerDailyGiftInfo {
    buyTime: number;           // 购买时间（秒级时间戳）
    lastClaimDay: number;      // 已领取到第几天 (0-6)
    lastClaimDate: number;     // 上次领取日期（YYYYMMDD）
}
```

### GiftInfo（推送给客户端的状态）

```typescript
interface GiftInfo {
    hasPurchased: boolean;
    buyTime: number;
    lastClaimDay: number;
    canClaimToday: boolean;
    remainingDays: number;
}
```

## 依赖模块

无（独立模块）

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| QUERY_CONFIG | queryNewPlayerDailyGiftConfig | From Client |
| CLAIM_DAILY_REWARD | claimDailyReward | From Client |
| ON_PURCHASED | onNewPlayerDailyGiftPurchased | To Client |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | `tblcpuserdata_cmnewplayerdailygift_xzmp`，name 字段: "NewPlayerDailyGiftInfo" |
| Redis Key | `mod(cp):name(cmnewplayerdailygift):appcode(xzmp):uid({uid}):NewPlayerDailyGiftInfo`，过期: 7天 |

## 核心流程

### 充值回调 (OnPayResult)

1. 判断 exchangeid 是否匹配配置的兑换商品
2. 检查是否已购买过（防止重复）
3. 发放第一天奖励（checkinReward[0]）
4. 记录购买时间和状态
5. 推送消息通知客户端

### 每日签到 (claimDailyReward)

1. 检查是否已购买
2. 检查今日是否已领取（比较 lastClaimDate）
3. 检查是否在有效期内（未超过 checkindays 天）
4. 发放当日奖励（checkinReward[lastClaimDay + 1]）
5. 更新 lastClaimDay 和 lastClaimDate

## 错误码

| 错误信息 | 说明 |
|---------|------|
| 礼包未启用 | 配置 isenable = 0 |
| 未购买礼包 | 玩家未购买迎新礼包 |
| 已领取完所有奖励 | 已领取全部7天奖励 |
| 今日已领取 | 当天已领取过 |
| 礼包已过期 | 超过 checkindays 天有效期 |
| 发放奖励失败 | 服务端发奖异常 |

## 常量定义

```typescript
const CONST_VAR = {
    MODULE_NAME: 'cmnewplayerdailygift',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}
```
```

- [ ] **Step 2: Commit**

```bash
git add CP-DEV/L3_cmnewplayerdailygift_xzmp.md
git commit -m "Add L3_cmnewplayerdailygift_xzmp: rewritten module detail from impl + code"
```

---

### Task 6: Delete impl documents

**Files:**
- Delete: `CP-DEV/doc/cmquickrecharge_xzmp_impl.md`
- Delete: `CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md`

- [ ] **Step 1: Delete both impl files**

```bash
rm CP-DEV/doc/cmquickrecharge_xzmp_impl.md
rm CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md
```

- [ ] **Step 2: Commit**

```bash
git add -u CP-DEV/doc/
git commit -m "Remove impl docs, replaced by L3 module details in CP-DEV root"
```
