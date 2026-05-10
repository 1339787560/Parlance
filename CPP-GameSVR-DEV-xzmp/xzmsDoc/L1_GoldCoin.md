# L1 金币接入 — xzms (金币血流六红中)

> 与 xzmo 共用 `NewDepositModule`。核心金币逻辑见 [xzmoDoc/L1_GoldCoin.md](../xzmoDoc/L1_GoldCoin.md)。

## xzms 特有差异

| 对比点 | xzmo | xzms |
|--------|------|------|
| NewDepositModule | 同源 | 同源 |
| 积分兑换 | — | `ScoreExchange.cpp` |
| 金币礼物 | — | `ShakeGiftModule` (摇礼物，使用金币) |
| 节日活动 | — | `FestivalActivity` (节日活动，可能关联金币奖励) |
| 比赛模块 | — | `TQMatchModule` (比赛消耗金币) |

### ScoreExchange

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/ScoreExchange.cpp` |
| 说明 | 非金币房间中的金豆(积分)兑换。与 NewDepositModule 互补 |

### 金币消费路径

```
金币充值(NewDepositModule)
    ├── 入场费(EnableEnterGameReq)
    ├── 比赛中扣除(FestivalActivity / TQMatchModule)
    ├── 摇礼物消费(ShakeGiftModule)
    └── 积分兑换(ScoreExchange — 金豆变金币)
```
