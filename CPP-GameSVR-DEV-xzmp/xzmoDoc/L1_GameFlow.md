# L1 游戏流程 — xzmo (金币血流血战)

> 版本象征名：**xzmo** | 源码路径：SVN `branches/douque/jinbi`
> 本版本侧重：**金币接入**、**金币金豆兼容**、**好友房**、**结算流程**。

---

## 生命周期概览

与 xzmo2 基本一致，差异点如下：

```
服务器启动
  → CGameServer_WithFriend 实例化(含好友房支持)
  → Initialize() → evSvrStart
      │
玩家匹配 → 可能走好友房随机桌
  → OnAskRandomTable (好友房版本有特殊路由)
      │
对局进行 → 麻将操作事件(xzmo2 相同)
      │
结算预处理 → evPreResult
  → NewDepositModule 注入金币结算(使用 GAME_RESULT_EXNEW)
  → 活动模块 OnPreResult (但金银版活动较少)
      │
最终结算 → OnGameWin()
  → CGameServer_WithFriend::OnGameWin() 覆写(好友房特殊结算)
  → NewDepositModule 提交金币变更
  → TransmitPBGameResult (PB 格式下发)
```

---

## 与 xzmo2 的关键流程差异

| 流程节点 | xzmo2 (银子) | xzmo (金币) |
|---------|-------------|------------|
| 服务器实例化 | `CMyGameServer` | `CGameServer_WithFriend` |
| 随机桌匹配 | 标准 `OnAskRandomTable` | 好友房版(可能被注释) |
| 结算结果类型 | `GAME_RESULT_EX` | `GAME_RESULT_EXNEW` |
| 结果序列化 | 原生结构体 | PB (protobuf) — `TransmitPBGameResult` |
| 金币处理 | 无 | `NewDepositModule` 贯穿进入→结算→离开 |
| 积分兼容 | 无 | 金币(新)与金豆(旧)双轨并行 |

---

## 核心事件类型

| 事件 | 说明 |
|------|------|
| `evPreResult` (NEW) | 使用 `GAME_RESULT_EXNEW` 类型，携金币字段 |
| `evOnGameWin` | 好友房覆写版本，额外处理 FR 结算 |
| `evPlayerGiveupGetDeposit` | 金币版特有：玩家放弃领取金币 |
| `evPlayerNewDepositNotEnough` | 金币版特有：金币不足 → 断线处理 |

---

## 货币体系

```
金豆/积分 (legacy)  ←→  金币 (new deposit)
     │                        │
     └────── 兼容层 ──────────┘
              │
        NewDepositModule
        ScoreExchange (积分兑换模块，xzms 中有)
```

---

## 好友房差异流程

```
标准房流程：创建桌子 → 进入 → 游戏 → 结算 → 离开
好友房流程：创建好友房 → 好友加入 → FR_游戏 → FR_结算(updateFrdRoomScore)
  → FR_离开(FR_CloseSoloTable) → FR_服务费(NotifyServiceFee)
```

详见 [L1_FriendRoom.md](L1_FriendRoom.md)。
