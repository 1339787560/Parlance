# Task: convert_xzmp 扩展 — 新手教程对局 (TqGameLesson)

## 概述

客户端（Creator）需要新手教程对局功能。新玩家（nBout==0）进入单机房完成教程后，客户端通过 `client_request('convert', cb, { req: 'claimTutorialReward' })` 请求发奖并标记完成。

**涉及文件：**
- `D:\Codlib\other\ModCPSvr\cpscript\src\xzmp\convert_xzmp.ts`
- `D:\Codlib\other\ModCPSvr\cpscript\src\xzmp\convert_xzmp.jsonc`

**设计文档（仅参考）：** Creator-Client-DEV-xzmp/doc/Test_CP_convert_TqGameLesson.md

---

## 1. MIGRATION_BIT + REQ_NAME 扩展

### 1.1 MIGRATION_BIT (line 35-42)

新增 bit 5，更新 ALL_DONE：

```typescript
const MIGRATION_BIT = {
    TQVIP: 0x01,
    TQMONTHCARD: 0x02,
    TQNEWPLAYERDAILYGIFT: 0x04,
    SCORE_COMPENSATE: 0x08,
    GOLD_COIN: 0x10,
    TQNEWPLAYERLESSON: 0x20,   // NEW: bit 5
    ALL_DONE: 0x3F,             // updated: 63
}
```

### 1.2 REQ_NAME (line 16-33)

新增两条：

```typescript
const REQ_NAME = {
    // ... existing ...
    QUERY_TUTORIAL_STATE: 'queryTutorialState',     // NEW
    CLAIM_TUTORIAL_REWARD: 'claimTutorialReward',   // NEW
}
```

---

## 2. MigrationResult 接口扩展 (line 53-58)

新增 `newPlayerLesson` 字段：

```typescript
interface MigrationResult {
    flags: number;
    levelInfo: any;
    monthCardInfo: any;
    giftInfo: any;
    newPlayerLesson?: {           // NEW
        isCompleted: boolean;
        rewardGold: number;
    }
}
```

---

## 3. OnClientRequest 处理

**插入位置：** `OnInternalCall` (line 123 `}`) 之后、`OnLogon` (line 125) 之前。

客户端通过 `client_request('convert', cb, { req: 'queryTutorialState' })` 和 `client_request('convert', cb, { req: 'claimTutorialReward' })` 发起请求，映射到 `OnClientRequest`。

签名参考 `cmdecoration_xzmp.ts:945` — `async function OnClientRequest(creq: modsvr.client_request, cresp: modsvr.client_response, cxt: modsvr.context)`。

```typescript
async function OnClientRequest(creq: modsvr.client_request, cresp: modsvr.client_response, cxt: modsvr.context) {
    let userid = creq.src.client.userid;
    let req_data = creq.req.data;
    let req_name = req_data['req'];

    if (req_name === REQ_NAME.QUERY_TUTORIAL_STATE) {
        let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
        let config = CommonFuncs.loadConfig();
        let isCompleted = (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0;
        cresp.resp.id = 1;
        cresp.resp.data = {
            isCompleted: isCompleted,
            rewardGold: isCompleted ? (config.newPlayerLessonReward ?? 0) : 0
        };
    } else if (req_name === REQ_NAME.CLAIM_TUTORIAL_REWARD) {
        let result = await Business.async_claimTutorialReward(cxt, userid);
        cresp.resp.id = result.success ? 1 : 0;
        cresp.resp.data = {
            success: result.success,
            rewardGold: result.rewardGold
        };
    }
}
```

---

## 4. Business.async_claimTutorialReward

在 `namespace Business` 中新增。

关键逻辑：先发奖（失败不影响标记），再设 bit。幂等设计。

```typescript
export async function async_claimTutorialReward(
    cxt: modsvr.context, userid: number
): Promise<{ success: boolean; rewardGold: number }> {
    let config = CommonFuncs.loadConfig();
    if (config.isenable == 0) return { success: false, rewardGold: 0 };

    let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
    let rewardGold = config.newPlayerLessonReward ?? 0;

    // 1. 先发奖励（失败不影响标记）
    let rewardOk = true;
    if (rewardGold > 0) {
        // 使用 modsvr 发奖能力。OnClientRequest 中可通过 creq.src 获取 src。
        // 可复用 async_batch_send_reward 或直接调 modsvr 接口
        // TODO: 确认具体发奖接口实现
        rewardOk = await Business.async_sendGoldCoin_internal(cxt, userid, rewardGold);
    }

    // 2. 设 bit（无论发奖结果）
    let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
    await CommonFuncs.async_setMigrationFlags(cxt, userid, newFlags);

    return { success: rewardOk, rewardGold };
}

// Placeholder — 需实现具体的发奖逻辑
// 参考 async_batch_send_reward 需要 src 参数
// 在 OnClientRequest 上下文中 creq.src 可用
export async function async_sendGoldCoin_internal(
    cxt: modsvr.context, userid: number, amount: number
): Promise<boolean> {
    // TODO: 实现发奖逻辑
    return true;
}
```

---

## 5. OnLogon 自动标记 (line 125-204)

### 5.1 在 gold coin migration 之后插入（line ~172）

gold coin migration 的代码范围是 line 160-172。在其 `}` 之后、line 176 注释之前插入：

```typescript
// 5. tutorial (bit 5) — auto-mark old players who never went through tutorial
if ((flags & MIGRATION_BIT.TQNEWPLAYERLESSON) === 0) {
    let bout = (logon as any).usergameinfo?.bout ?? 0;
    if (bout > 0) {
        // Has game records but no tutorial bit → auto-complete (no reward)
        flags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
    }
}
```

### 5.2 修改 final push（line ~201-203）

当前：
```typescript
result.flags = flags;
CommonFuncs.notifyClient(src, cxt, userid, REQ_NAME.MIGRATION_RESULT, result);
```

改为：
```typescript
result.flags = flags;
result.newPlayerLesson = {
    isCompleted: (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0,
    rewardGold: config.newPlayerLessonReward ?? 0,
};
CommonFuncs.notifyClient(src, cxt, userid, REQ_NAME.MIGRATION_RESULT, result);
```

---

## 6. convert_xzmp.jsonc 配置

新增：

```jsonc
{
    "isenable": 1,
    "guid": "convert_xzmp",
    // ... existing ...
    "newPlayerLessonReward": 100000
}
```

---

## 7. 接口契约

### 7.1 OnClientRequest: queryTutorialState

| 方向 | 格式 |
|------|------|
| 请求 | `{ req: 'queryTutorialState' }` |
| 成功响应 | `cresp.resp = { id: 1, data: { isCompleted: boolean, rewardGold: number } }` |
| 失败 | `cresp.resp = { id: 0, data: {} }` |

### 7.2 OnClientRequest: claimTutorialReward

| 方向 | 格式 |
|------|------|
| 请求 | `{ req: 'claimTutorialReward' }` |
| 成功响应 | `cresp.resp = { id: 1, data: { success: true, rewardGold: number } }` |
| 已标记/重复请求 | 幂等，返回 `{ id: 1, data: { success: true, rewardGold: config值 } }` |
| 禁用 | `isenable == 0` → `{ id: 0, data: {} }` |

### 7.3 OnLogon push (migrationResult_convert_xzmp)

```typescript
{
    req: 'migrationResult_convert_xzmp',
    data: {
        flags: number,
        // ... existing fields ...
        newPlayerLesson: {
            isCompleted: boolean,
            rewardGold: number,
        }
    }
}
```

---

## 8. 测试要点

### 8.1 单元测试

| # | 测试 | 期望 |
|---|------|------|
| 1 | `MIGRATION_BIT.TQNEWPLAYERLESSON === 0x20` | 不与其他 bit 重叠 |
| 2 | `ALL_DONE === 0x3F` | 6 bits 全 OR |
| 3 | queryTutorialState, bit 未设 | `{ isCompleted: false, rewardGold: 0 }` |
| 4 | queryTutorialState, bit 已设 | `{ isCompleted: true, rewardGold: config值 }` |
| 5 | claimTutorialReward, 首次 | 设 bit 5, 发奖, `{ success: true, rewardGold }` |
| 6 | claimTutorialReward, 重复请求 | 幂等返回 success，不多发奖励 |
| 7 | claimTutorialReward, 发奖失败 | bit 仍设, `{ success: false, rewardGold }` |
| 8 | claimTutorialReward, isenable==0 | `{ id: 0, data: {} }`, 无状态变更 |
| 9 | OnLogon, nBout=0, bit 未设 | bit 保持 0, push isCompleted=false |
| 10 | OnLogon, nBout>0, bit 未设 | bit 自动标记, push isCompleted=true |
| 11 | OnLogon, nBout>0, bit 已设 | bit 不变, push isCompleted=true |

### 8.2 现有 TestTool 扩展

可在 `TestTool` namespace 中新增测试方法 `async_testTutorialLesson()`，复用 `async_testOnLogon` 的模式，构造 mock logon 数据验证自动标记逻辑。

运行方式：`NODE_TLS_REJECT_UNAUTHORIZED=0 node --loader ts-node/esm ... src/xzmp/convert_xzmp.ts`

---

## 9. 设计约束提醒

1. `OnClientRequest` 是新函数，文件中尚无此 handler — 需新建（参考 cmdecoration_xzmp.ts 的相同模式）
2. 发奖逻辑 `async_sendGoldCoin_internal` 需确认使用哪个 modsvr 内部接口
3. OnLogon 自动标记**不发奖励**，仅设 bit
4. 奖励仅在客户端主动调用 `claimTutorialReward` 时才发放
5. 所有操作幂等：重复 claim 不会多发奖励，重复 OnLogon 不会重复标记
