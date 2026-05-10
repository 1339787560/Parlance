# L1 金币接入 — xzmo / xzms 共用

> 金币版核心模块：`NewDepositModule`。金币（新充值货币）与金豆（积分/legacy 货币）双轨并行。

---

## NewDepositModule

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/NewDepositModule.h` / `.cpp` |
| 模式 | 单例 `GetInstance()` |
| 数据 | `hash_userid2newdeposit` (玩家金币映射), `roomconfig` (房间配置) |
| 通信 | `imMsg2ChunkByMove`, `imMsg2ChunkByCopy`, `imSendUserResponse` |

### 核心功能

```
进入游戏 → EnableNewDeposit(roomid) ──no──→ 走金豆(旧)逻辑
              │ yes
              ↓
         检查房间区间 FitRoomRange()
              │
              ↓
         获取玩家金币 GetPlayerNewDeposit(userid)
              │
              ↓
         游戏结算 PushToNewDepositResult()
              │ (PRE_RESULT / FINAL_RESULT 两阶段)
              ↓
         通知客户端更新 evNotifyNewDepositUpdate
```

### 关键接口

| 接口 | 说明 |
|------|------|
| `GetPlayerNewDeposit(userid, low, high)` | 获取玩家金币(64位拆为两个32位，兼容老协议) |
| `ReqPlayerNewDeposit(userid)` | 从 ChunkSvr 请求玩家金币 |
| `PushToNewDepositResult(table, ..., GAME_RESULT_EXNEW, ..., res_type)` | 推送结算结果（PRE_RESULT 预处理 → FINAL_RESULT 最终） |
| `EnableNewDeposit(roomid)` | 判断房间是否启用金币模式 |
| `getRoomRange(roomid, min, max)` | 获取房间金币上限/下限 |
| `OnPlayerUpdate(userid, newDeposit)` | 更新本地缓存的金币值 |

### 事件

| 事件 | 触发时机 |
|------|----------|
| `OnServerStart` | 注册 Chunk 消息回调 |
| `OnChunkStart` | ChunkClient 就绪后注册 |
| `OnNodeRegsiterOK` | 节点注册完成 |
| `evNotifyNewDepositUpdate` | 金币变更时通知 CMyGameServer |

---

## 金币 vs 金豆(积分)兼容

```
金豆(积分) — 老系统             金币 — 新系统
    │                                │
    ├─ GAME_RESULT_EX (旧结构)       ├─ GAME_RESULT_EXNEW (新结构)
    ├─ nDepositDiffs (32位)         ├─ 64位金币字段
    └─ SafeDeposit (保险箱)         └─ 独立金币账户
```

兼容策略：
- 非金币房间（`EnableNewDeposit = false`）走旧金豆逻辑
- 金币房间使用 `GAME_RESULT_EXNEW`、64位金币值
- I32_I64Tool 联合体做高低位转换（`OnI32toI64` / `OnI64toI32`）

---

## 房间配置

`tqroom::RoomConfigItem` (protobuf) 定义了房间的金币范围：
- `nMinLimit` / `nMaxLimit` — 进入房间的最低/最高金币要求
- 配置通过 `GetRoomConfigByRoomID(roomid)` 获取

---

## 积分兑换 (ScoreExchange)

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/ScoreExchange.cpp` (xzms 中) |
| 说明 | 非金币房间中，金豆(积分)兑换逻辑 |
