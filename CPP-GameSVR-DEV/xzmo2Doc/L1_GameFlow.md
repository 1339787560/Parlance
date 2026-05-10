# L1 对局流程 — xzmo2 (银子血流血战)

> 源码路径：`D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit\gamesvr\`

---

## 生命周期概览

```
服务器启动(_tmain)
  → CMyGameServer 实例化 → Initialize()
    → evSvrStart 通知所有模块
    → 模块各自初始化(Chunk连接、预定义数据加载等)
      │
玩家进入房间 → OnEnterGame() → 房间匹配 → StartSoloTable()
  → evCPStartSoloTable 通知模块
      │
游戏开始 → OnStartGame() → OnStartGameEx()
  → evCPGameStarted / evNewTable 通知
  → 洗牌、发牌
      │
对局进行(循环)
  ├── 定缺(拍卖) → evMJAuctionBanker
  ├── 抓牌 → evMJCatch
  ├── 出牌 → evMJThrow
  ├── 碰 → evMJPeng (含 PrePeng → Peng 两阶段)
  ├── 杠 → evMJAnGang / evMJMnGang / evMJPnGang
  ├── 胡 → evMJHu
  └── 过 → evMJGuo
      │
结算预处理 → evPreResult (活动模块在此注入奖励)
  → 各模块 OnPreResult 回调
      │
最终结算 → OnGameWin()
  → evOnGameWin / evOnCPGameWin / evTransmitGameResultEx
  → GameLogData 记录对局日志
  → 模块 OnCPGameWin 回调(活动奖励结算)
      │
服务器关闭 → Shutdown() → evShutdown
```

---

## 事件路由链

麻将操作消息通过 `CMJServer::OnRequest()` 的 switch-case 分流：

```cpp
// mj/MjServer.cpp
switch (lpRequest->head.nRequest) {
    CASE_REQUEST_HANDLE(GR_CATCH_CARD, OnCatchCard)
    CASE_REQUEST_HANDLE(GR_THROW_CARDS, OnThrowCards)
    CASE_REQUEST_HANDLE(GR_PREPENG_CARD, OnPrePengCard)
    CASE_REQUEST_HANDLE(GR_HU_CARD, OnHuCard)
    CASE_REQUEST_HANDLE(GR_AUCTION_BANKER, OnAuctionBanker)
    // ... 重建消息处理
    CASE_REQUEST_HANDLE(GR_RECONS_CHI_CARD, OnReconsChiCard)
    // ...
    default: __super::OnRequest(lpParam1, lpParam2);
}
```

未匹配的消息 fallback 到父类 `CCommonBaseServer::OnRequest()`。

---

## 核心事件类型

| 事件 | 类型 | 触发时机 | 响应模块 |
|------|------|----------|----------|
| `evSvrStart` | `(BOOL&, TcyMsgCenter*)` | 服务器初始化 | ChunkClient, Predefine, GameLogData, Module 等 |
| `evCPGameStarted` | `(CCommonBaseTable*, void*)` | 游戏开始 | 排行、任务、道具、新手抽奖等 |
| `evCPStartSoloTable` | `(START_SOLOTABLE*, ...)` | 桌子创建 | 同上 |
| `evNewTable` | `(CCommonBaseTable*)` | 新桌子建立 | GameLogData, GameHuUnitsMaker |
| `evPreResult` | `(LPCONTEXT_HEAD, CMyGameTable*, int, int, int, GAME_RESULT_EX*, int)` | 结算前 | 活动模块注入奖励 |
| `evOnGameWin` | `(LPCONTEXT_HEAD, CRoom*, CTable*, int, BOOL, int)` | 结算完成 | 活动模块发放奖励 |
| `evOnCPGameWin` | `(LPCONTEXT_HEAD, int, CCommonBaseTable*, void*)` | 结算(CP通道) | GameLogData, DataRecord |
| `evTransmitGameResultEx` | `(CCommonBaseTable*, ..., LPGAME_RESULT_EX, int)` | 结果下发 | DataRecord, GameLogData |
| `evShutdown` | `()` | 服务器关闭 | ChunkClient, GameLogData 等 |

---

## 模块注册顺序 (initComponent)

模块在 `GameSvr.cpp` 中按顺序注册：

1. DumpUnhandleException / TcyInputTest — 基础设施
2. CPredefine — 全局配置
3. GameToChunkClient / GameToChunklogClient — 通信层
4. MySysMsgToServer — 消息分发
5. CMyExPlayerInfoDelegate — 玩家信息
6. GameSvrModule — 消息过滤转发
7. CMyExTaskDelegate / CMyExWxTaskDelegate — 任务系统
8. GameLogData — 游戏日志(结算记录)
9. GameHuUnitsMaker — 胡牌单元
10. CRobotPlayerDataDelegate — 机器人数据
11. CTreasureDelegate — 宝箱
12. PropsAddtion — 道具加成
13. DataRecord — 数据统计
14. CDoubleEggDelegate — 双蛋活动
15. CNoviceLotteryDelegate — 新手抽奖
16. WinStreakModule — 连胜
17. Ranklist — 排行
18. SwitchRoomModule — 换房
19. DailyFirstWinModule — 每日首胜
