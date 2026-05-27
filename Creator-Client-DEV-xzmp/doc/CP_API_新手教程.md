# CP API 接口文档 — 新手教程对局

> 模块：`convert`（`src/xzmp/convert_xzmp.ts`）
> 目标客户端：Creator（四川麻将 xzmp）

---

## 背景

迁移模块 `convert` 负责将旧平台玩家的数据迁移至 Creator 平台。其中 **bit 5（TQNEWPLAYERLESSON）** 用于追踪玩家是否已完成新手教程对局。

- 有对局记录（`usergameinfo.bout > 0`）的老玩家，登录时自动标记为"已通过"，**不发奖励**
- 无对局记录的新玩家，bit 5 保持 0，由客户端引导走新手教程
- 通过客户端请求 `claimTutorialReward` 领取教程完成奖励

---

## 1. 查询教程状态

客户端请求 CP，查询当前玩家新手教程对局的完成状态。

### 请求

| 字段 | 值 |
|------|-----|
| 消息名 | `queryTutorialState` |
| 方向 | Client → CP |

```json
{
    "req": "queryTutorialState"
}
```

### 响应

```json
{
    "id": 1,
    "data": {
        "isCompleted": false,
        "rewardGold": 160000
    }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `isCompleted` | `boolean` | 是否已完成新手教程对局（bit 5 已标记） |
| `rewardGold` | `number` | 教程完成奖励金币数。`isCompleted=false` 时也为实际值，客户端可用于展示 |

---

## 2. 领取教程奖励

当玩家完成新手教程对局后，由客户端调用此接口领取奖励。

### 请求

| 字段 | 值 |
|------|-----|
| 消息名 | `claimTutorialReward` |
| 方向 | Client → CP |

```json
{
    "req": "claimTutorialReward"
}
```

### 响应

```json
// 成功
{
    "id": 1,
    "data": {
        "success": true,
        "rewardGold": 160000
    }
}

// 模块未启用
{
    "id": 0,
    "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `boolean` | 发奖是否成功 |
| `rewardGold` | `number` | 实际发放的金币数 |

**幂等安全**：重复请求不会重复发奖，但均返回 `success: true`。

---

## 3. 登录迁移通知

玩家登录时 CP 执行数据迁移，迁移完成后通过通知告知客户端结果（含教程状态）。

### 通知

| 字段 | 值 |
|------|-----|
| 消息名 | `migrationResult_convert_xzmp` |
| 方向 | CP → Client |
| 触发时机 | 玩家登录后，迁移流程完成时 |

```json
{
    "req": "migrationResult_convert_xzmp",
    "data": {
        "flags": 63,
        "levelInfo": { /* ... */ },
        "monthCardInfo": { /* ... */ },
        "giftInfo": { /* ... */ },
        "newPlayerLesson": {
            "isCompleted": true,
            "rewardGold": 160000
        }
    }
}
```

**教程相关字段（`newPlayerLesson`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `isCompleted` | `boolean` | 教程对局是否已完成（bit 5 已标记） |
| `rewardGold` | `number` | 教程完成奖励金币数 |

客户端应根据 `isCompleted` 决定是否展示/引导新手教程。

---

## 4. 迁移标记位说明

| bit | 常量 | 值 | 含义 |
|-----|------|----|------|
| 5 | `TQNEWPLAYERLESSON` | `0x20` | 新手教程对局已完成 |

`ALL_DONE = 0x3F`（全部 6 个 bit 置位，含 bit 0~5）。

---

## 5. 配置项

配置文件：`convert_xzmp.jsonc`

```jsonc
{
    "isenable": 1,
    // 新手教程对局奖励金币数
    "newPlayerLessonReward": 160000,
    // ...
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `isenable` | `number` | 模块开关：1=启用，0=禁用 |
| `newPlayerLessonReward` | `number` | 教程完成奖励金币数量 |

---

## 6. 客户端流程图

```
玩家登录
    │
    ├─ CP 执行 OnLogon 迁移
    │   ├─ bout > 0 且 bit 5 = 0 → 自动标记 bit 5（不发奖励）
    │   └─ bout = 0 → bit 5 保持 0
    │
    ├─ CP 推送 migrationResult_convert_xzmp（含 newPlayerLesson）
    │
    └─ 客户端：
        ├─ isCompleted = true  → 不引导教程，可展示"奖励已领取"
        └─ isCompleted = false → 引导走新手教程对局
                                    │
                                    └─ 教程完成后调用 claimTutorialReward
                                        ├─ 成功 → 展示奖励
                                        └─ 失败 → 重试
```

---

*文档版本：2026-05-26*
