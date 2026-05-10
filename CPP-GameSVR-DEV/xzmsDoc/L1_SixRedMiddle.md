# L1 六红中玩法 — xzms (金币血流六红中)

> 源码路径：`D:\Codlib\douque\xzmx\xzmsPC\branches\pve\zhong\gamesvr\`

---

## 六红中 vs 血流血战

| 对比点 | 血流血战 (xzmo2) | 血流六红中 (xzms) |
|--------|-----------------|-------------------|
| 癞子/红中 | 无特殊牌 | 六张红中作为特殊牌 |
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
| 配置 | `makecard.ini` (游戏服目录) |

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
