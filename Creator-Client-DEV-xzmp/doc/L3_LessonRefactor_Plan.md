# L3 新手教程重构计划 — 单机模式流程对齐联机

> **状态**: ✅ 全部 Phase 实现完成 (2026-05-28)

## 背景

当前新手教程实现 (`CMNewPlayerLessonCtrl` / `CMNewPlayerLessonData`) 存在以下核心问题：

1. ~~Lesson 逻辑散落在 GameConnect~~ → **Phase 0/6 已修复**
2. ~~消息注入走 simulateMessage 绕路~~ → **Phase 1 已修复**
3. ~~CUSTOM 消息绕过真实流程~~ → **Phase 1 已修复**
4. ~~WaitForAll 模式脆弱~~ → **Phase 2 已修复**
5. ~~出牌阶段没有区分 rsp/ntf~~ → **Phase 3 已修复**

## 重构目标

1. **单机模式流程与联机完全一致**：所有阶段都使用 `sendReq → rsp` + `ntf` 路径
2. **Lesson 逻辑集中在 LessonCtrl**：GameConnect 不感知 lesson 模式
3. **仅 LessonData 定义差异**：联机 vs 单机的区别仅在于「消息来源」— 联机来自 socket，单机来自 LessonData 调度器
4. **可测试、可验证**：每个阶段有明确的完成标准

---

## 已实现的改动清单

### GameConnect.ts
| 行 | 改动内容 |
|----|---------|
| 6 | 删除 `import { getLessonCtrl }` |
| 858-862 | sendExchange3Cards: `isSinglePlayerRoom()` 检查 + 事件 emit（替代 lesson 拦截） |
| 1268-1272 | sendAuctionBanker: `isSinglePlayerRoom()` 检查 + 事件 emit（替代 lesson 拦截） |
| 1344-1348 | sendThrowCards: `isSinglePlayerRoom()` 检查 + 事件 emit |

### game-event.ts
| 行 | 改动内容 |
|----|---------|
| 388 | 新增 `onLessonSendExchange3Cards` |
| 390 | 新增 `onLessonSendAuctionBanker` |
| 392 | 新增 `onLessonSendThrowCards` |

### CMNewPlayerLessonCtrl.ts
| 变更 | 说明 |
|------|------|
| 删除 `_waitingPlayerAction`, `_pendingActionType`, `_pendingActionDone`, `_exchangeHandledByNtf` | Phase 2 WaitForAll 清理 |
| 新增 `_waitingForPlayerInput` | Phase 5 出牌等待 |
| 新增 `dispatchToGC()` | Phase 1 直调 handler 分发表 |
| 新增 `setupHooks()` | Phase 0 注册事件钩子 |
| 替换 `injectNotify` | Phase 1 从 simulateMessage 改为 dispatchToGC |
| 删除 `markActionDone`, `onPlayerActionComplete`, `markExchangeHandledByNtf` | Phase 2 废弃方法 |
| 删除 `EXCHANGE_REMOVE`, `EXCHANGE_FINISHED_NTF`, `DINGQUE_FINISHED_NTF` 的 CUSTOM 处理 | Phase 7 |
| WAIT_PLAYER_ACTION 改为顺序暂停语义 | Phase 5 |

### CMNewPlayerLessonData.ts
| Stage | 改动 |
|-------|------|
| Stage 3 (换三张) | 删除 WAIT_PLAYER_ACTION 消息，waitForAll 计数由事件钩子处理 |
| Stage 4 (换三张完成) | 从 CUSTOM 改为 NOTIFY (GR_EXCHANGE3CARDS_FINISHED) |
| Stage 5 (定缺) | 删除 WAIT_PLAYER_ACTION 消息，waitForAll 计数由事件钩子处理 |
| Stage 6 (定缺完成) | 从 CUSTOM 改为 NOTIFY (GR_AUCTION_FINISHED) |
| Stage 7,9,10,11 | 玩家自动出牌 → WAIT_PLAYER_ACTION 等待真人操作 |

### CMNewPlayerLessonDef.ts
| 变更 | 说明 |
|------|------|
| 删除 `EXCHANGE_REMOVE`, `EXCHANGE_FINISHED_NTF`, `DINGQUE_FINISHED_NTF` | 废弃 CUSTOM ID |
| `PlayerActionType` 简化为仅 `THROW_CARD` | 其他类型 PHASE 2 后不再使用 |

## 核心流程变化

### 换三张阶段（重构后）

```
玩家选择换三张 → sendExchange3Cards()
  → isSinglePlayerRoom() → emit(onLessonSendExchange3Cards)
  → LessonCtrl 钩子: 更新本地状态 + 玩家操作完成计数

LessonData Stage 3: 3 条机器人 GR_SYSTEMMSG 并行派发
  → 每条走 ntfSystemmsg → ntfExchange3Cards
  → 每个 NOTIFY 派发 +1 waitForAll 计数

当 waitForAll 计数达到 4 → 自动进入 Stage 4
  → injectNotify(GR_EXCHANGE3CARDS_FINISHED) → ntfExchange3Finished
```

### 定缺阶段（重构后）

```
玩家选择定缺 → sendAuctionBanker()
  → isSinglePlayerRoom() → emit(onLessonSendAuctionBanker)
  → LessonCtrl 钩子: 更新定缺状态 + 玩家操作完成计数

LessonData Stage 5: 3 条机器人 GR_SYSTEMMSG 并行派发
  → 每条走 ntfSystemmsg → ntfDingQue
  → 每个 NOTIFY 派发 +1 waitForAll 计数

当 waitForAll 计数达到 4 → 自动进入 Stage 6
  → injectNotify(GR_AUCTION_FINISHED) → ntfDingqueFinished
```

### 出牌阶段（重构后）

```
LessonData 派发 MJ_GR_CARD_CAUGHT (玩家摸牌)
  → injectNotify → dispatchToGC → ntfCardCaught
→ WAIT_PLAYER_ACTION → _waitingForPlayerInput = true (暂停)

玩家点击手牌 → sendThrowCards(cardId)
  → isSinglePlayerRoom() → emit(onLessonSendThrowCards)
  → LessonCtrl 钩子: injectNotify(MJ_GR_CARDS_THROW)
  → _waitingForPlayerInput = false → nextStep()

LessonData 继续派发 AI 摸牌/出牌消息...
```

---

## 执行顺序

| 阶段 | 状态 | 风险 |
|------|------|------|
| **0** 提取 LessonAction 管道 | ✅ 完成 | 低 |
| **1** 直调 ntf/rsp Handler | ✅ 完成 | 中 |
| **2** WaitForAll 重构 | ✅ 完成 | 中 |
| **3** 出牌 rsp/ntf 分离 | ✅ 完成 | 中 |
| **5** 玩家等待机制 | ✅ 完成 | 中 |
| **6** GameConnect 剥离 | ✅ 完成 | 低 |
| **7** CUSTOM 清理 | ✅ 完成 | 低 |
| **8** 代码清理 | ✅ 完成 | 低 |

## 总改动文件

| 文件 | 改动量 |
|------|--------|
| `game/scripts/lesson/CMNewPlayerLessonCtrl.ts` | 大量改动 |
| `game/scripts/lesson/CMNewPlayerLessonDef.ts` | 中等改动 |
| `game/scripts/lesson/CMNewPlayerLessonData.ts` | 中等改动 |
| `game/scripts/network/GameConnect.ts` | 少量改动 |
| `game/scripts/event/game-event.ts` | 少量改动 |

## 不涉及的文件

以下文件未修改：
- `Game.ts` — 教程启动逻辑不变
- `GameInfo.ts` — 教程相关接口不变
- `HallPlugin.ts` — 教程状态管理不变
- `GamePlugin.ts` — 教程启动注册不变
- `LessonCtrlRegistry.ts` — 注册逻辑不变
- `ResultManager.ts` — 结算拦截逻辑不变
