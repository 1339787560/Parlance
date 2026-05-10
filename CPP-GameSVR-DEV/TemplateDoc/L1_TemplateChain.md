# L1 模板继承链

> 三个游戏服务版本共享的模板代码结构。模板位于 `D:\LibraryVC12_P\tcgMJ2.0\trunk\`。
> 各版本代码路径不同，但 `commonBase/`、`mj/`、`my/` 三层继承结构是统一的。

---

## 完整继承层级

```
CMainServer (XYGame 框架, 模板库基类)
│
├── CMjServer (TCGMJNT/tcgsvrmj2.h)     ← 模板层：麻将服务器基类
│   └── 处理：吃/碰/杠/胡/过/出牌/抓牌 协议路由
│   └── 通知：NotfiyAuctionBanker, NotifyCardsThrow, NotifyCardCaught 等
│
└── CCommonBaseServer (commonBase/)      ← 版本公共层
    └── 继承：CMainServer + CommonServerEvent
    └── 事件：evSvrStart, evCPGameStarted, evOnCPGameWin, evShutdown 等
    │
    └── CMJServer (mj/)                  ← 麻将事件层
        └── 继承：CCommonBaseServer + MJServerEvent
        └── 事件：evMJPeng, evMJHu, evMJThrow, evMJAuctionBanker 等
        │
        └── CMyGameServer (my/)          ← 游戏业务层（版本差异核心在此）
            ├── xzmo2 (银子)：CMyGameServer : CMJServer, MYGameServerEvent
            └── xzms (金币六红中)：CMyGameServer : CMJServer, MYGameServerEvent
                └── CGameServer_WithFriend : virtual CMyGameServer  ← 好友房扩展


CTable (XYGame 框架)
└── CMjTable (TCGMJ/tcgmj2.h)           ← 模板层：麻将桌子
    └── 函数：MJ_CanPeng/MJ_CanChi/MJ_CanHu/MJ_CanAnGang 等全局牌型判定
    └── CCommonBaseTable / CMyGameTable  ← 版本桌子
```

---

## 模板文件索引

| 文件 | 路径 | 说明 |
|------|------|------|
| CMjServer | `TCGMJNT/tcgsvrmj2.h` | 麻将服务器模板：处理客户端麻将操作协议，通知客户端桌面消息 |
| CMjTable | `TCGMJ/tcgmj2.h` | 麻将桌子模板：牌墙构建、洗牌、吃碰杠胡判定函数 |
| 牌型函数 | `TCGMJ/tcgmj2.h` (全局) | `MJ_CanPeng`/`MJ_CanChi`/`MJ_CanMnGang`/`MJ_CanAnGang`/`MJ_CanHua`/`MJ_CanHu` |

---

## 版本继承链差异

### xzmo2 (银子血流血战)

```
CMainServer
└── CCommonBaseServer : CMainServer, CommonServerEvent
    └── CMJServer : CCommonBaseServer, MJServerEvent
        └── CMyGameServer : CMJServer, MYGameServerEvent   ← 终点
```
- `CMyGameServer` 即最终使用的服务器类（`_tmain` 中实例化 `CMyGameServer`）
- 无好友房层，无 PB 支持
- MYGameServerEvent 较简单

### xzmo (金币血流血战)

继承链预估与 xzms 类似（代码同源，金币版 → SVN）。
```
CMainServer
└── ... 
    └── CMyGameServer : CMJServer, MYGameServerEvent
        └── CGameServer_WithFriend : virtual CMyGameServer  ← 好友房
```

### xzms (金币血流六红中)

```
CMainServer
└── CCommonBaseServer : CMainServer, CommonServerEvent
    └── CMJServer : CCommonBaseServer, MJServerEvent
        └── CMyGameServer : CMJServer, MYGameServerEvent
            └── CGameServer_WithFriend : virtual CMyGameServer  ← 好友房
```
- `_tmain` 非服务模式下实例化 `CGameServer_WithFriend` 而非 `CMyGameServer`
- 好友房层覆写了 `TransmitGameResult`、`OnNewTable`、`OnGameEntered` 等

### 关键差异对比

| 对比点 | xzmo2 (银子) | xzms (金币六红中) |
|--------|-------------|-------------------|
| 最终服务类 | `CMyGameServer` | `CGameServer_WithFriend` |
| 好友房支持 | 无 | 有（`FR_CloseSoloTable`, `FR_ThinkExitSucceed`） |
| 结算结果类型 | `GAME_RESULT_EX` | `GAME_RESULT_EXNEW` |
| PB 支持 | 无 | 有（`PB_NotifyOneUser`, `PB_NotifyTablePlayers` 等） |
| 金币系统 | 无 | `NewDepositModule`, `OnPlayerNewDepositCurrency`, `updateCoinData` |
| 模块管理器 | 无 | `CModuleManager m_modules` |
| 跨游戏服通信 | 无 | `GameSvrNodeClient` |
| 断线恢复 | 无 | `BrokenModel` |
| CMyGameServer 大小 | ~180 行 | ~340 行 |

---

## 事件驱动模式

所有模块通过 `initComponent()` 注册，连接服务器事件：

```cpp
mainServer->evSvrStart    += delegate(module, &Module::OnServerStart);
mainServer->evCPGameStarted += delegate(module, &Module::OnCPGameStarted);
mainServer->evOnGameWin   += delegate(module, &Module::OnCPGameWin);
mainServer->evPreResult   += delegate(module, &Module::OnPreResult);
```

游戏流程触发顺序：
1. `evSvrStart` → 模块初始化
2. `evCPGameStarted` → 游戏开始
3. 麻将操作事件 (`evMJPeng`/`evMJHu`/`evMJThrow` 等) → 对局进行
4. `evPreResult` → 结算前预处理（活动模块注入奖励/扣费逻辑）
5. `evOnGameWin` / `evOnCPGameWin` → 最终结算记录
