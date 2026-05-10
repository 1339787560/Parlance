# L1 结算流程 — xzmo (金币血流血战)

> 金币版结算流程核心差异：使用 `GAME_RESULT_EXNEW` (64位金币支持)，经由 PB 序列化下发。

---

## 结算链路

```
游戏结束(胡牌/流局)
      │
      ↓
PreSaveResult() — 结算预处理
  → evPreResult (使用 GAME_RESULT_EXNEW)
  → 各模块 OnPreResult:
      ├── NewDepositModule::PushToNewDepositResult(PRE_RESULT)
      ├── TQMatchModule::OnPreResult
      ├── ShakeGiftModule::OnPreResult
      └── FestivalActivity::OnPreResult
      │
      ↓
CheckInGameResult() — 结果校验
      │
      ↓
OnGameWin() — CGameServer_WithFriend 覆写版
  → CalcResultWinOrLoss() — 计算输赢
  → BulidScoreResults() — 构建分数结果
  → updateFrdRoomScore() — 好友房分数更新
  → NotifyServiceFee() — 服务费通知
  → TransmitPBGameResult() — PB 序列化结果
      │
      ↓
evOnGameWin / evOnCPGameWin
  → 模块 OnCPGameWin:
      ├── NewDepositModule::PushToNewDepositResult(FINAL_RESULT)
      ├── GameLogData::OnCPGameWin (记录对局日志)
      ├── DataRecord::OnCPGameWin (数据统计)
      └── 其他模块...
      │
      ↓
TransmitGameResult() — FR 版下发到客户端
  → evTransmitGameResultEx
  → evTransmitGameResultWithFlag
```

---

## GAME_RESULT_EX vs GAME_RESULT_EXNEW

| 字段 | GAME_RESULT_EX (银版) | GAME_RESULT_EXNEW (金币版) |
|------|----------------------|---------------------------|
| 金币支持 | 无 | 64位金币值 |
| 长度 | 较短 | 扩展字段更多 |
| 新旧兼容 | — | I32_I64Tool 高低位转换 |
| PB 序列化 | 不支持 | 支持 PB_NotifyTablePlayers 等 |

---

## 结算数据记录 (GameLogData)

GameLogData 继承于 `DataLogerModule`，在结算时记录两类日志：

- **XZ 日志** (血流战)：`PLAYRECORDFORLOG_XZ` → 记录总对局数、总血战数、底注、输赢倍数
- **XL 日志** (血流)：`PLAYRECORDFORLOG_XL` → 记录胡牌次数、总血流数、输赢倍数

关键字段：
```cpp
nBeginDeposit — 开始金币
nLeftDeposit (nOldDeposits + nDepositDiffs) — 剩余金币
nDepositOpValue — 对局操作金币变化量
nWinMultiple — 输赢倍数
```

---

## 结算中的货币处理

```
CalcResultWinOrLoss()
  → 计算每个座位的 nDepositDiffs
      │
      ├── 金币模式：NewDepositModule 处理 64位金币
      └── 金豆模式：走旧逻辑 (32位)
      │
      ↓
TransmitPBGameResult()
  → 序列化为 PB 格式
  → PB_NotifyTablePlayers() 发送给客户端
  → 客户端展示结算界面
```
