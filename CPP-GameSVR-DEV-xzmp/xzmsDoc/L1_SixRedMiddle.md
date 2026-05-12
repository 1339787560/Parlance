# L1 六红中玩法 — xzms (金币血流六红中)

> 源码路径：`D:\Codlib\douque\xzmx\xzmsPC\branches\pve\zhong\gamesvr\`

---

## 六红中 vs 血血流战

| 对比点 | 血血流战 (xzmo2) | 血流六红中 (xzms) |
|--------|-----------------|-------------------|
| 稞子/红中 | 无特殊牌 | 六张红中作为特殊牌 |
| 做牌模块 | `MakeCardV2.hpp` | `MakeCardNewModule` + `MakeCardNewDef.h` |
| 胡牌判定 | 标准 `GameHuUnitsMaker` | 自有胡牌逻辑 + `localai/MJUnitsCardTool` |
| AI 引擎 | 无本地 AI | `CLoaclAIManager` (本地 AI 管理) |
| 红包玩法 | 无 | 可能关联(六红中玩法变体) |

---

## 做牌模块 (MakeCardNewModule)

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/MakeCardNewModule.h` / `.cpp` |
| 模式 | 单例 `GetInstance()` |
| 事件 | `OnServerStart`, `OnChunkStart` |
| 说明 | 做牌测试模块 — 构造特定牌型用于测试验证 |
| 配置 | `makecard.ini` (游戏服目目录) |

关键接口：
- `imGetCurDir` — 获取当前目录(用于 makecard.ini 文件监听)
- `imRegisterFileMod` — 注册文件修改监听(`TcyFileModListener`)
- `imLookupUserData` / `imGetTablePtr` — 查找玩家数据和桌子

---

## 本地 AI 引擎

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/localai/LoaclAI.h` (推测) |
| 说明 | 本地 AI 用于机器人托管和测试，包含 `MJUnitsCardTool` 牌型工具 |
| 接入 | `initComponent()` 中注册到 `evSvrStart` / `evNewTable` |

AI 操作接口：
```cpp
localAiMgr->imRobotGuoCard       = &CMyGameServer::OnRobotGuoCard
localAiMgr->imSeverAutoPlayFangChongHu = &CMyGameServer::OnSeverAutoPlayFangChongHu
localAiMgr->imSeverAutoPlayHuQiangGang = &CMyGameServer::OnSeverAutoPlayHuQiangGang
localAiMgr->imSeverAutoPlayHuZiMo     = &CMyGameServer::OnSeverAutoPlayHuZiMo
```

---

## 特有模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 做牌新模块 | `MakeCardNewModule.cpp` | 六红中做牌测试 |
| 本地 AI | `localai/LoaclAI.h` | AI 托管引擎 |
| 牌型工具 | `localai/MJUnitsCardTool.h` | 手牌组合分析工具 |
| 做牌配置 | `makecard.ini` | 牌型配置文件 |
| 文件监听 | `tcycomponents/TcyFileModListener.h` | 监听 makecard.ini 热更新 |

---

## 与 xzmo2 的模块差异

| xzmo2 有 / xzms 无 | xzms 有 / xzmo2 无 |
|---------------------|---------------------|
| `DailyFirstWinModule` | `NewDepositModule` (金币) |
| `SwitchRoomModule` | `GameSvrNodeClient` (跨服通信) |
| `GameSvrModule` | `BrokenModel` (断线恢复) |
| `DoubleEggDelegate` | `FestivalActivity` (节日活动) |
| `NoviceLotteryDelegate` | `TQMatchModule` (比赛匹配) |
| `TreasureDelegate` | `ShakeGiftModule` (摇礼物) |
| | `MakeCardNewModule` (做牌) |
| | `CLoaclAIManager` (本地 AI) |
| | `ScoreExchange` (积分兑换) |
| | `Module` / `Module.h` (模块管理) |

---

## 文件监听热更新

xzms 引入 `TcyFileModListener` 用于做牌配置热更新：
```cpp
auto fileListenMod = GetEntity().assign<TcyFileModListener>();
mainSvr->evShutdown += delegate(fileListenMod, &TcyFileModListener::OnServerStop);
```

做牌模块注册文件修改监听，当 `makecard.ini` 变化时自动重新加载，无需重启服务。

---

## 已知踩坑

### 1. CMyGameTable 无 Restart 覆写，开局入口是 RestartEx

**坑点**：CMyGameTable 没有覆写 `Restart`（父类 CMJTable::Restart 参数为 int 版本）。xzms 金币版实际开局入口是 `RestartEx`（参数为 int64_t 版本）。文档/口头提到"CMyGameTable 的 Restart"时，实际应指向 RestartEx。

**Why**：CMJTable::Restart 适配银版(int 参数)，RestartEx 适配金版(int64_t 参数)。xzms 只走 RestartEx。

**How to apply**：凡涉及"开局时记录数据"，应在 RestartEx 中添加，而非 Restart。RestartEx 内 `m_dwGameStart = GetTickCount()` 位于 early-return 之后，仅在游戏真正开始时才执行。

### 2. IsGameWinFlag 是瞬态标志，仅 TransmitGameResultExNew 前后为 TRUE

**坑点**：`SetGameWinFlag(TRUE)` 仅在 `TransmitGameResultExNew` 调用前设置，调用后立即 `SetGameWinFlag(FALSE)`。IsGameWinFlag 在 ConstructPBGameResult 内为 TRUE，函数返回后立刻变回 FALSE。

**Why**：游戏框架用 IsGameWinFlag 区分 PRE_RESULT(中途结算) vs FINAL_RESULT(最终结算)。

**How to apply**：依赖 IsGameWinFlag 的逻辑必须在 ConstructPBGameResult 内直接计算（如 isover），不能缓存后在外部使用。

### 3. 秒级时间戳不能用 m_dwGameStart (GetTickCount) 直接换算

**坑点**：代码已有 `m_dwGameStart = GetTickCount()`（毫秒级 tick），但秒级时间戳需用 `time(NULL)`（epoch 秒）。GetTickCount 和 time(NULL) 基准不同，不能互减。需在 BOUTDATACACHE 新增 `nGameStartTime_` 存储 `time(NULL)` 值。

**Why**：GetTickCount 从系统启动算，time(NULL) 从 epoch 算。两者不能交叉运算。

**How to apply**：凡需"秒级时间差"，存储开始时刻的 `time(NULL)` 值，结束时再 `time(NULL)` 相减。

### 4. getPlayerDeposit 调用时序影响 isbroke 判断

**坑点**：在 ConstructPBGameResult 中调用 `getPlayerDeposit()` 时，deposit 值取决于结算流水时序。PRE_RESULT(中途结算) 时 deposit 可能已部分更新（上一轮结算结果已写入），FINAL_RESULT 时为最终 deposit。

**Why**：血流模式多次结算，每次结算后 deposit 即被更新。下次结算读到的是上一轮结算后的值。

**How to apply**：isbroke 判断基于当前 deposit 值（调用时刻的值），而非"结算后理论值"。若需严格"结算后是否归零"，需用 `nOldScore + nScoreDiff` 计算。
