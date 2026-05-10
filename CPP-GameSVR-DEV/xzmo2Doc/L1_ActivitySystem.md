# L1 活动系统 — xzmo2 (银子血流血战)

> 源码路径：`D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit\gamesvr\`
> 所有活动模块遵循统一模式：实现 `OnPreResult` + `OnCPGameWin`(或 `OnCPGameStarted`) 两个回调。

---

## 活动模块清单

### 百变双蛋 (DoubleEggDelegate)

| 属性 | 值 |
|------|-----|
| 文件 | `commonBase/DoubleEggDelegate.cpp` |
| 事件 | `evOnCPGameWin` (结算触发), `evPreResult` (预处理) |
| 说明 | 双蛋活动 — 根据对局结果触发双蛋奖励发放 |
| 通信 | `imMsg2Chunk` → 发往 ChunkSvr 处理奖励逻辑 |

### 连胜 (WinStreakModule)

| 属性 | 值 |
|------|-----|
| 文件 | `WinStreakModule.cpp` |
| 事件 | `evOnGameWin` (结算触发), `evPreResult` (预处理) |
| 说明 | 玩家连胜记录与奖励。在 `OnPreResult` 中校验连胜条件，`OnCPGameWin` 中发放连胜奖励 |
| 通信 | `imMsg2Chunk` → 通知 ChunkSvr |

### 每日首胜 (DailyFirstWinModule)

| 属性 | 值 |
|------|-----|
| 文件 | `DailyFirstWinModule.cpp` |
| 事件 | `evOnGameWin` (结算触发), `evPreResult` (预处理) |
| 说明 | 每日首次胜利额外奖励。在 `OnPreResult` 中判断当日是否已领取，`OnCPGameWin` 中发放 |
| 通信 | `imMsg2Chunk` → 通知 ChunkSvr |

### 新手抽奖 (NoviceLotteryDelegate)

| 属性 | 值 |
|------|-----|
| 文件 | `commonBase/NoviceLotteryDelegate.cpp` |
| 事件 | `evCPGameStarted` (游戏开始), `evCPStartSoloTable` (桌子创建) |
| 说明 | 新手抽奖活动 — 跟踪玩家游戏次数，触发抽奖资格 |
| 测试 | `evInput` (测试命令) |

### 宝箱 (TreasureDelegate)

| 属性 | 值 |
|------|-----|
| 文件 | `commonBase/TreasureDelegate.cpp` |
| 事件 | `evCPGameStarted`, `evCPStartSoloTable` (游戏开始/桌子创建) |
| 说明 | 宝箱系统 — 在游戏开始时检查宝箱状态，通过 ChunkSvr 处理宝箱逻辑 |
| 通信 | `imMsg2Chunk` + `imNotifyOneUser` |

### 排行榜 (Ranklist)

| 属性 | 值 |
|------|-----|
| 文件 | `Ranklist.cpp` |
| 事件 | `evCPGameStarted` (游戏开始), `evCPStartSoloTable` (桌子创建) |
| 说明 | 排行榜分数更新。`UpdateRankScore()` 在游戏开始时计算排名分数。结算相关回调已被注释（可能后期移除） |
| 通信 | `imMsg2Chunk` |

### 道具加成 (PropsAddtion)

| 属性 | 值 |
|------|-----|
| 文件 | `commonBase/PropsAddtion.cpp` |
| 事件 | `evPreResult` (结算前), `evOnGameWin` (结算完成), `evCPGameStarted` |
| 说明 | 道具加成分数 — 在 `evPreResult` 中计算道具倍数，`evOnGameWin` 中应用加成 |
| 通信 | `imMsg2Chunk` |

### 换房模块 (SwitchRoomModule)

| 属性 | 值 |
|------|-----|
| 文件 | `SwitchRoomModule.cpp` |
| 事件 | `evSvrStart` (服务器启动初始化) |
| 说明 | 房间切换功能 — 提供 `gImAuoMsgToClient` 自动发消息给客户端处理换房逻辑 |

---

## 活动模块通用模式

```
module.OnPreResult(table, ...)    → 校验条件，准备奖励数据
module.OnCPGameWin(table, ...)    → 发放奖励，通知 ChunkSvr
```

或：

```
module.OnCPGameStarted(table, ...)   → 初始化活动状态
module.OnCPStartSoloTable(...)       → 单人桌创建时的活动逻辑
```

所有活动模块通过 `imMsg2Chunk` 函数对象与 ChunkSvr 通信，奖励发放逻辑在 ChunkSvr 侧完成。

---

## 其他辅助模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 任务系统 | `my/MyTaskDelegate.h` | 任务(杠/胡/碰/赢)追踪，通过 evTaskGang/evTaskHu/evTaskPeng 等专用事件 |
| 微信任务 | `my/MyWxTaskDelegate.h` | 微信任务，额外关注 evWxTaskHu 和 evWinDeposit |
| 机器人数据 | `commonBase/RobotPlayerDataDelegate.h` | 跟踪机器人对局数据 |
| 胡牌单元 | `../common/mj/GameHuUnitsMaker.h` | 胡牌组合构造器 |
