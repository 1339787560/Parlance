# L3 新手教程重构计划 — 单机模式流程对齐联机

## 背景

当前新手教程实现 (`CMNewPlayerLessonCtrl` / `CMNewPlayerLessonData`) 存在以下核心问题：

1. **Lesson 逻辑散落在 GameConnect**：`sendExchange3Cards`、`sendAuctionBanker` 中有 inline 的 lesson 拦截代码，GameConnect 承担了双份职责
2. **消息注入走 simulateMessage 绕路**：NOTIFY 消息通过 socket.simulateMessage 注入，而非直接调用 ntf handler
3. **CUSTOM 消息绕过真实流程**：`EXCHANGE_FINISHED_NTF` / `DINGQUE_FINISHED_NTF` 不是走 ntf 路径，而是 CUSTOM 内直接调用 `(GameConnect as any).ntfExchange3Finished(bs)` — 与联机流程不一致
4. **WaitForAll 模式脆弱**：`_pendingActionDone` hack 标记玩家在派发前完成操作，状态管理复杂
5. **出牌阶段没有区分 rsp/ntf**：LessonData 中出牌消息全部写死为 NOTIFY，未对应联机流程的 `sendThrowCards → rspThrowCards → ntfCardsThrow`

## 重构目标

1. **单机模式流程与联机完全一致**：所有阶段都使用 `sendReq → rsp` + `ntf` 路径
2. **Lesson 逻辑集中在 LessonCtrl**：GameConnect 不感知 lesson 模式
3. **仅 LessonData 定义差异**：联机 vs 单机的区别仅在于「消息来源」— 联机来自 socket，单机来自 LessonData 调度器
4. **可测试、可验证**：每个阶段有明确的完成标准

---

## 阶段 0：预备 — 提取 LessonAction 管道

**目标**：消除 GameConnect 中的 lesson 拦截代码，建立统一的「单机操作管道」。

### 0.1 现状问题

```typescript
// GameConnect.sendExchange3Cards — 当前
let lessonCtl = getLessonCtrl();
if (lessonCtl && lessonCtl.isRunning()) {
    GameInfo.setPlayerSelectStatus(GameInfo.getMyChairNO());
    GameInfo.setExchange3Cards(exchangeCards);
    eventCenter.emit(GameEvent.onConfirmExchange, GameInfo.getMyDrawIndex());
    if (lessonCtl.isWaitingPlayerAction() && lessonCtl.getPendingActionType() === 1) {
        lessonCtl.onPlayerActionComplete(1);
    } else {
        lessonCtl.markActionDone(1);
    }
    return; // 跳过真实发送
}
```

`sendExchange3Cards` 同时处理联机和单机两种模式，职责混合。

### 0.2 目标方案

所有 send* 方法**不感知 lesson 模式**。LessonCtrl 通过事件监听接管操作：

```typescript
// GameConnect.sendExchange3Cards — 重构后
// ... 构造 data, 序列化, sendRequest ...
ct.mjGameCenter?.socket?.sendRequest(
    GameReqDef.GR_EXCHANGE_CARDS, 
    bs.GetBuffer(), 
    this.rspExchange3Cards.bind(this)
);
```

LessonCtrl 注册 `GameEvent.onPlayerAction` 监听，在收到玩家的操作意图后：

```typescript
// CMNewPlayerLessonCtrl — 新增
onPlayerAction(actionType: PlayerActionType, data?: any) {
    // 1. 构造 rsp 数据 → 模拟联机回包
    // 2. 调用对应的 rsp handler
    // 3. 注入 ntfSystemmsg → GameConnect.ntfExchange3Cards
    // 4. 推进 waitForAll 计数
}
```

### 0.3 改动清单

| 文件 | 改动 |
|------|------|
| `GameConnect.sendExchange3Cards` | 删除 860-876 行 lesson 拦截 |
| `GameConnect.sendAuctionBanker` | 删除 1282-1297 行 lesson 拦截 |
| `CMNewPlayerLessonCtrl` | 新增 `onPlayerAction()` 代替 markActionDone/onPlayerActionComplete |
| `CMNewPlayerLessonDef` | 新增 `PlayerActionResponse` 接口定义 rsp/ntf 数据映射 |

### 0.4 验证

- 联机模式：`sendExchange3Cards` 正常走 socket 发送
- 单机模式：`sendExchange3Cards` 发送 req 后，LessonCtrl 拦截到事件，模拟 rsp 回调

---

## 阶段 1：LessonData 消息直调 ntf/rsp Handler

**目标**：NOTIFY/RSP 消息不再走 `simulateMessage` 绕路，改为直接调用 GameConnect 的 handler 方法。

### 1.1 现状问题

当前 `injectNotify` 通过 `socket.simulateMessage(msgID, buffer)` 注入消息，消息经过以下路径：

```
injectNotify → socket.simulateMessage → addHandler 回调 → GameConnect.ntfCardsThrow
```

这绕了一个大圈，且要求 socket 上已经注册了 handler。更关键的是，反序列化在 `serializeLessonMsg` 中提前做了，而 handler 中再次反序列化，存在双重解析隐患。

### 1.2 目标方案

LessonData 的消息直接调用 GameConnect 的对应 ntf/rsp 方法：

```typescript
// CMNewPlayerLessonCtrl — 替换 injectNotify
private injectNotify(msgID: number, datatbl: any) {
    let bs = serializeLessonMsg(msgID, datatbl);
    if (!bs) return;
    
    // 直接调用 handler，而非走 socket 模拟
    switch (msgID) {
        case GameReqDef.MJ_GR_CARDS_THROW:
            (GameConnect as any).ntfCardsThrow(bs.GetBuffer());
            break;
        case GameReqDef.MJ_GR_CARD_CAUGHT:
            (GameConnect as any).ntfCardCaught(bs.GetBuffer());
            break;
        // ... 完整映射
    }
}
```

或者在 GameConnect 上将 ntf 方法提取为公共接口：

```typescript
// GameConnect — 新增静态方法
static dispatchNotify(msgID: number, buffer: ArrayBuffer) {
    // 根据 msgID 分发到对应 handler
    // 等价于 addHandler 回调的行为，但不需要 socket
}
```

### 1.3 EXCHANGE_FINISHED_NTF / DINGQUE_FINISHED_NTF 统一

当前这两个消息作为 CUSTOM 处理，**直接调用了 GameConnect 的私有方法**：

```typescript
case CUSTOM_ID.EXCHANGE_FINISHED_NTF:
    let bs = ct.serialize(datatbl, 'EXCHANGE3CARDSINNER');
    bs.SetPos(0);
    (GameConnect as any).ntfExchange3Finished(bs); // ← 绕过真实流程
    break;
```

重构后，它们应该作为 NOTIFY 消息，走统一的 inject 路径：

```typescript
// LessonData Stage 4 — 从 CUSTOM 改为 NOTIFY
{
    msgID: GameReqDef.GR_EXCHANGE3CARDS_FINISHED, // ← 真实 msgID
    msgType: LessonMsgType.NOTIFY,
    delay: 0.5,
    datatbl: { /* 同现有数据 */ },
}
```

这样 `injectNotify` 会匹配 `GR_EXCHANGE3CARDS_FINISHED` → 序列化为 EXCHANGE3CARDSINNER → 分发到 `ntfExchange3Finished`，与联机流程完全一致。

### 1.4 联机 vs 单机对比

| 阶段 | 联机 | 单机（重构后） |
|------|------|---------------|
| 玩家换三张 | sendRequest → rspExchange3Cards | sendExchange3Cards（不走网络）→ LessonCtrl 构造 rsp → rspExchange3Cards |
| 其他玩家换三张 | ntfSystemmsg → ntfExchange3Cards | injectNotify(GR_SYSTEMMSG, ...) → ntfSystemmsg → ntfExchange3Cards |
| 换三张完成 | ntfExchange3Finished | injectNotify(GR_EXCHANGE3CARDS_FINISHED, ...) → ntfExchange3Finished |
| 玩家定缺 | sendAuctionBanker → rspAuctionBanker | sendAuctionBanker（不走网络）→ LessonCtrl 构造 rsp → rspAuctionBanker |
| 其他玩家定缺 | ntfSystemmsg → ntfDingQue | injectNotify(GR_SYSTEMMSG, ...) → ntfSystemmsg → ntfDingQue |
| 定缺完成 | ntfDingqueFinished | injectNotify(GR_AUCTION_FINISHED, ...) → ntfDingqueFinished |
| 玩家摸牌 | rspCatchCard → ntfCardCaught | injectNotify(MJ_GR_CARD_CAUGHT, ...) → ntfCardCaught |
| 玩家出牌 | sendThrowCards → rspThrowCards → ntfCardsThrow | injectNotify(MJ_GR_CARDS_THROW, ...) → ntfCardsThrow |
| AI 摸牌/出牌 | ntfCardCaught / ntfCardsThrow | injectNotify(→) → ntfCardCaught / ntfCardsThrow |

### 1.5 改动清单

| 文件 | 改动 |
|------|------|
| `CMNewPlayerLessonCtrl.ts` | `serializeLessonMsg()` 扩展支持所有 msgID |
| `CMNewPlayerLessonCtrl.ts` | `injectNotify()` 从 simulateMessage 改为直调 handler |
| `CMNewPlayerLessonCtrl.ts` | `processCustom` 删除 EXCHANGE_FINISHED_NTF / DINGQUE_FINISHED_NTF 分支 |
| `CMNewPlayerLessonData.ts` | Stage 4 消息类型从 CUSTOM 改为 NOTIFY (GR_EXCHANGE3CARDS_FINISHED) |
| `CMNewPlayerLessonData.ts` | Stage 6 消息类型从 CUSTOM 改为 NOTIFY (GR_AUCTION_FINISHED) |
| `CMNewPlayerLessonDef.ts` | 删除 EXCHANGE_FINISHED_NTF / DINGQUE_FINISHED_NTF 枚举值 |

### 1.6 验证

- ntfExchange3Finished 被正确调用（不经过 CUSTOM path）
- ntfDingqueFinished 被正确调用
- 所有现有 NOTIFY 消息（出牌、摸牌、系统消息）走新路径仍正常工作
- 换三张动画仍正常播放，定缺标志仍正常展示

---

## 阶段 2：WaitForAll 重构 — 并行阶段计数统一

**目标**：消除 `_pendingActionDone` hack，使用统一的完成计数机制。

### 2.1 现状问题

当前并行阶段有 4 个「完成信号」：
- 3 个机器人：各自的 NOTIFY 消息派发完毕后各计 1（在 `processMessage` 中 `_parallelCompletionCount++`）
- 1 个真人玩家的 WAIT_PLAYER_ACTION

但 WAIT_PLAYER_ACTION 可能发生顺序颠倒：
1. 玩家操作快于 WAIT_PLAYER_ACTION 派发 → 用 `_pendingActionDone` + `markActionDone()` 提前标记
2. WAIT_PLAYER_ACTION 派发后检查 `_pendingActionDone` → 如果已标记则直接推进
3. WAIT_PLAYER_ACTION 先派发 → `_waitingPlayerAction = true` → 等 `onPlayerActionComplete`

这种「不知道谁先到」的处理引入了复杂的双重状态。

### 2.2 目标方案

并行阶段的完成信号统一调整为：「消息派发完毕即算完成 1 个信号」。

```
waitForAll = 4 的含义：
- 3 个机器人 NOTIFY（GR_SYSTEMMSG 派发完毕）= 3 个完成信号
- 1 个真人操作（sendExchange3Cards/sendAuctionBanker 被调用）= 1 个完成信号
```

关键变化：**WAIT_PLAYER_ACTION 不再是 CUSTOM 等待消息，而是被 remove 掉**。真人玩家的操作通过拦截 sendExchange3Cards/sendAuctionBanker 调用即可。

```typescript
// CMNewPlayerLessonDef — 删除 WAIT_PLAYER_ACTION 枚举
```

LessonData 的并行阶段变为：
```typescript
// Stage 3: 换三张 — 仅 3 条机器人 NOTIFY
{
    parallel: true,
    waitForAll: 4, // 3 条 NOTIFY + 1 次 sendExchange3Cards 调用
    messages: [
        // 3 条机器人 GR_SYSTEMMSG（同现有）
    ],
    // 删除 WAIT_PLAYER_ACTION 消息
}
```

LessonCtrl 注册全局的「操作前置钩子」：

```typescript
// CMNewPlayerLessonCtrl — 操作监听
setupOperationHooks() {
    // 这里的 operateType 操作都会自动增加完成计数
    // EXCHANGE_3CARDS: 1 次 sendExchange3Cards 算 1 个完成信号
    // DINGQUE: 1 次 sendAuctionBanker 算 1 个完成信号
}
```

当玩家调用 `sendExchange3Cards` 时（Phase 0 后不再在 GameConnect 拦截），LessonCtrl 通过事件拦截：

```typescript
// CMNewPlayerLessonCtrl
onBeforeSendExchange3Cards() {
    if (this._parallelWaitForAll > 0) {
        // 记录玩家操作完成信号
        this._parallelCompletionCount++;
        this.tryAdvanceParallelStage();
    }
}
```

### 2.3 优点

- 无需 `_pendingActionDone` / `_pendingActionType` / `_waitingPlayerAction` 三个状态
- GameConnect 不再感知 lesson 模式
- 完成计数只增不减，逻辑线性

### 2.4 改动清单

| 文件 | 改动 |
|------|------|
| `CMNewPlayerLessonDef.ts` | 删除 `WAIT_PLAYER_ACTION` 枚举值 |
| `CMNewPlayerLessonData.ts` | Stage 3 删除 WAIT_PLAYER_ACTION 消息 |
| `CMNewPlayerLessonData.ts` | Stage 5 删除 WAIT_PLAYER_ACTION 消息 |
| `CMNewPlayerLessonCtrl.ts` | 删除 `_waitingPlayerAction`, `_pendingActionType`, `_pendingActionDone` |
| `CMNewPlayerLessonCtrl.ts` | 删除 `onPlayerActionComplete()`, `markActionDone()` |
| `CMNewPlayerLessonCtrl.ts` | 新增 `onOperationCalled(actionType)` — 被 send* 方法调用 |
| `CMNewPlayerLessonCtrl.ts` | 删除 `processCustom` 中 WAIT_PLAYER_ACTION 分支 |

---

## 阶段 3：出牌阶段 rsp/ntf 分离

**目标**：LessonData 中出牌阶段的消息区分联机的 rsp 和 ntf 路径。

### 3.1 现状问题

当前 LessonData 出牌阶段所有消息都是 NOTIFY：

```typescript
// Stage 7 — 当前
{ msgID: MJ_GR_THROW_CARDS, msgType: LessonMsgType.RSP, ... },  // ← 正确
{ msgID: MJ_GR_CARD_CAUGHT, msgType: LessonMsgType.NOTIFY, ... }, // ← 联机时这里是 rspCatchCard 或 ntfCardCaught
{ msgID: MJ_GR_CARDS_THROW, msgType: LessonMsgType.NOTIFY, ... },  // ← 联机时这里是 ntfCardsThrow
```

### 3.2 目标方案

出牌阶段的 LessonData 严格遵循联机协议：

**AI 出牌 → 玩家摸牌 → 玩家出牌 → AI 摸牌 → AI 出牌**：

```typescript
// AI 出牌轮
// AI (chair 0) 出牌 → 联机: ntfCardsThrow
{ msgID: MJ_GR_CARDS_THROW, msgType: LessonMsgType.NOTIFY, delay: pd(), datatbl: { nChairNO:0, ... } },
// 玩家轮到出牌 → 联机: rspThrowCards (bNextChair=3)
{ msgID: MJ_GR_THROW_CARDS, msgType: LessonMsgType.RSP, delay: sd(), datatbl: { nNextChair: 3 } },
// 玩家摸牌 → 联机: ntfCardCaught (或 rspCatchCard)
{ msgID: MJ_GR_CARD_CAUGHT, msgType: LessonMsgType.NOTIFY, delay: sd(), datatbl: { nChairNO:3, ... } },
// 玩家出牌 → 玩家操作 (WAIT_PLAYER_ACTION) 而非自动 NOTIFY
// 玩家操作完成后 → 注入 ntfCardsThrow
// AI 摸牌 → 联机: ntfCardCaught
{ msgID: MJ_GR_CARD_CAUGHT, msgType: LessonMsgType.NOTIFY, delay: sd(), datatbl: { nChairNO:2, ... } },
// AI 出牌 → 联机: ntfCardsThrow
```

**AI 出牌 → AI 摸牌 → AI 出牌**（非玩家轮次）：

```typescript
// AI 出牌
{ msgID: MJ_GR_CARDS_THROW, msgType: LessonMsgType.NOTIFY, delay: pd(), datatbl: { nChairNO:0, ... } },
// AI 摸牌
{ msgID: MJ_GR_CARD_CAUGHT, msgType: LessonMsgType.NOTIFY, delay: sd(), datatbl: { nChairNO:1, ... } },
// AI 出牌
{ msgID: MJ_GR_CARDS_THROW, msgType: LessonMsgType.NOTIFY, delay: pd(), datatbl: { nChairNO:1, ... } },
```

**玩家摸牌后需要玩家操作的轮次**：

```typescript
// 玩家摸牌 → 通过 NOTIFY (联机时 ntfCardCaught)
{ msgID: MJ_GR_CARD_CAUGHT, msgType: LessonMsgType.NOTIFY, delay: sd(), datatbl: { nChairNO:3, ... } },
// CUSTOM WAIT_PLAYER_ACTION — 等待真人出牌
{ msgID: CUSTOM_ID.WAIT_PLAYER_ACTION, msgType: LessonMsgType.CUSTOM, delay: 0,
    datatbl: { actionType: PlayerActionType.THROW_CARD } },
```

### 3.3 PlayerActionType 扩展

```typescript
// CMNewPlayerLessonDef.ts — 扩展
export enum PlayerActionType {
    EXCHANGE_3CARDS = 1,
    DINGQUE = 2,
    THROW_CARD = 3,
    HU = 4,
    PASS = 5,
    PENG = 6,
    GANG = 7,
}
```

### 3.4 改动清单

| 文件 | 改动 |
|------|------|
| `CMNewPlayerLessonDef.ts` | 扩展 `PlayerActionType` 枚举 |
| `CMNewPlayerLessonDef.ts` | 恢复 `WAIT_PLAYER_ACTION` 枚举 |
| `CMNewPlayerLessonData.ts` | Stage 7-13 出牌轮次的消息类型按联机协议重新标注 |
| `CMNewPlayerLessonData.ts` | 玩家需要操作的轮次插入 `WAIT_PLAYER_ACTION` |
| `CMNewPlayerLessonCtrl.ts` | WAIT_PLAYER_ACTION 逻辑恢复，取消 _pendingActionDone 机制 |

---

## 阶段 4：碰杠胡走消息序列

**目标**：碰杠胡不需要特殊 CUSTOM 分支，跟随 LessonData 序列执行。

### 4.1 现状

当前 LessonData 中没有碰杠胡的消息序列，整个对局只有出牌和胡牌。

### 4.2 设计方案

如果需要碰杠胡场景，在 LessonData 中添加对应的消息：

| 操作 | msgID | msgType | 联机协议 |
|------|-------|---------|---------|
| 碰 | MJ_GR_CARD_PENG | NOTIFY | 联机: ntfCardPeng |
| 明杠 | MJ_GR_CARD_MN_GANG | NOTIFY | 联机: ntfCardMnGang |
| 暗杠 | MJ_GR_CARD_AN_GANG | NOTIFY | 联机: ntfCardAnGang |
| 补杠 | MJ_GR_CARD_PN_GANG | NOTIFY | 联机: ntfCardPnGang |
| 胡牌 | MJ_GR_GAME_WIN | NOTIFY | 联机: ntfGameWin |

### 4.3 改动清单（此阶段按需执行）

| 文件 | 改动 |
|------|------|
| `CMNewPlayerLessonData.ts` | 按需添加碰杠胡消息序列 |
| `CMNewPlayerLessonCtrl.ts` | 在 `serializeLessonMsg` 中注册新的 msgID 序列化 |

---

## 阶段 5：出牌阶段 — 真实玩家等待机制

**目标**：轮到真实玩家出牌时，暂停 LessonData 派发，等待玩家操作后恢复。

### 5.1 现状

当前 `sendThrowCards` 中：
- 联机模式：发送请求 → rspThrowCards → 出牌模拟 → ntfCardsThrow
- 当前单机模式：直接 emit 本地事件（无真实等待）

### 5.2 目标方案

单机模式中 `sendThrowCards` 与联机流程一致：

```typescript
// sendThrowCards — 重构后（无 lesson 拦截）
// 构造 data，序列化
// 发送 → 这里不走真实 socket，但 LessonCtrl 通过事件接管
```

LessonCtrl 拦截 `sendThrowCards`（类似 Phase 0 的拦截模式）：

```typescript
// CMNewPlayerLessonCtrl — 处理玩家出牌
onBeforeSendThrowCards(cardId: number) {
    if (!this._running) return false; // 不拦截
    
    // 1. 模拟联机 rspThrowCards
    // 2. 构造 ntfCardsThrow 数据
    // 3. 注入 ntfCardsThrow
    this.injectNotify(GameReqDef.MJ_GR_CARDS_THROW, {
        nChairNO: GameInfo.getMyChairNO(),
        nCardIDs: [cardId],
        // ... 其他字段从 lessonData 的预期数据中读取
    });
    
    // 4. 如果当前在 WAIT_PLAYER_ACTION 状态，恢复推进
    this.resumeFromPlayerAction(PlayerActionType.THROW_CARD);
    
    return true; // 已拦截
}
```

### 5.3 WAIT_PLAYER_ACTION 生命周期

```
LessonData 派发到 WAIT_PLAYER_ACTION
  → _waitingPlayerAction = true, _pendingActionType = THROW_CARD
  → 暂停派发，等待玩家操作

玩家点击出牌
  → GameConnect.sendThrowCards(cardId)
  → LessonCtrl.onBeforeSendThrowCards(cardId) 拦截
    → 注入模拟 rsp + ntf
    → resumeFromPlayerAction()
      → _waitingPlayerAction = false
      → 恢复 LessonData 派发下一消息
```

### 5.4 改动清单

| 文件 | 改动 |
|------|------|
| `CMNewPlayerLessonCtrl.ts` | 新增 `onBeforeSendThrowCards()` / `resumeFromPlayerAction()` |
| `CMNewPlayerLessonCtrl.ts` | 恢复 `WAIT_PLAYER_ACTION` 在 `processCustom` 中的处理 |

---

## 阶段 6：GameConnect 剥离 Lesson 提及

**目标**：GameConnect 中没有任何 `getLessonCtrl()` 引用。

### 6.1 现状

`sendExchange3Cards` 和 `sendAuctionBanker` 中引用：

```typescript
let lessonCtl = getLessonCtrl();
```

`getLessonCtrl` 函数来自 lesson 模块的全局引用。

### 6.2 目标方案

GameConnect 不引用任何 lesson 模块。单机接管通过以下任一方式：

**方案A（推荐）：事件钩子**

```typescript
// GameConnect.sendExchange3Cards — 重构后
public sendExchange3Cards(count: number, exchangeCards: number[]): void {
    // 发送一个事件，允许监听方课前处理
    let cancelled = eventCenter.emit(GameEvent.onBeforeSendExchange3Cards, count, exchangeCards);
    if (cancelled) return; // LessonCtrl 返回 true 表示已拦截
    
    // 原有逻辑（联机）
    // ...
}
```

**方案B：代理模式**

```typescript
// 创建 GameConnectProxy
class GameConnectProxy {
    private _real: GameConnect;
    private _lessonCtrl: CMNewPlayerLessonCtrl | null;
    
    sendExchange3Cards(...) {
        if (this._lessonCtrl?.isRunning()) {
            this._lessonCtrl.handleSendExchange3Cards(...);
            return;
        }
        this._real.sendExchange3Cards(...);
    }
}
```

推荐方案A，更轻量，不需要修改调用链。

### 6.3 改动清单

| 文件 | 改动 |
|------|------|
| `GameConnect.ts` | `sendExchange3Cards` 删除 lesson 拦截代码，改为 emit 事件 |
| `GameConnect.ts` | `sendAuctionBanker` 删除 lesson 拦截代码，改为 emit 事件 |
| `CMNewPlayerLessonCtrl.ts` | 新增 `setupHooks()` — 注册事件监听 |
| `CMNewPlayerLessonCtrl.ts` | 实现 `onBeforeSendExchange3Cards` / `onBeforeSendAuctionBanker` 事件处理 |

---

## 阶段 7：删除或保留 CUSTOM 消息

**目标**：评估每个 CUSTOM 消息的必要性。

### 7.1 CUSTOM 消息清单

| 当前 ID | 用途 | 保留？ | 原因 |
|---------|------|--------|------|
| BETTERCARD (1) | 提示出牌建议 | 保留 | UI 引导，无联机对应 |
| GETREWARD (2) | 领奖 | 保留 | 领奖后走 CP 接口 |
| LESSONOVER (3) | 结束 | 保留 | 结束清理 |
| FIRSTHU (4) | 首次胡牌提示 | 保留 | UI 引导，无联机对应 |
| CANHUTINGINFO (5) | 可以胡牌提示 | 保留 | UI 引导，无联机对应 |
| NOTCALQYS (6) | 不计缺一色 | 保留 | 标记游戏模式 |
| MATCHING (10) | 匹配提示 | 保留 | UI 动画显示 |
| EXCHANGE_REMOVE (11) | 移除手牌 | **删除** | 由 ntfExchange3Finished 替代完成手牌更新 |
| WAIT (12) | 等待 | 保留 | 纯延迟 |
| WAIT_PLAYER_ACTION (13) | 等待真人 | 保留（调整） | 真人等待 |
| EXCHANGE_FINISHED_NTF (14) | 换三张完成 | **删除** | 阶段 1 改为 NOTIFY |
| DINGQUE_FINISHED_NTF (15) | 定缺完成 | **删除** | 阶段 1 改为 NOTIFY |

### 7.2 EXCHANGE_REMOVE 的替代方案

当前 EXCHANGE_REMOVE 用于在换三张时从手牌移除换出的牌。删除后：
- `ntfExchange3Finished` 内部已经通过 `GameInfo.setReceiverd3Card()` + `exchange3Cards` 数据调整处理了手牌更新
- 所以 `EXCHANGE_REMOVE` 是冗余的

### 7.3 改动清单

| 文件 | 改动 |
|------|------|
| `CMNewPlayerLessonDef.ts` | 删除 `EXCHANGE_REMOVE`, `EXCHANGE_FINISHED_NTF`, `DINGQUE_FINISHED_NTF` |
| `CMNewPlayerLessonData.ts` | 删除使用 `EXCHANGE_REMOVE` 的 CUSTOM 消息 |
| `CMNewPlayerLessonCtrl.ts` | 删除 `processCustom` 中对应分支 |
| `CMNewPlayerLessonCtrl.ts` | 删除 `_exchangeHandledByNtf` 相关代码 |

---

## 阶段 8：代码清理与冗余删除

**目标**：删除所有因上述重构变得无用的变量、方法、注释。

| 文件 | 删除项 |
|------|--------|
| `CMNewPlayerLessonCtrl.ts` | `_pendingActionDone` 字段 |
| `CMNewPlayerLessonCtrl.ts` | `markActionDone()` 方法 |
| `CMNewPlayerLessonCtrl.ts` | `_exchangeHandledByNtf` 字段 |
| `CMNewPlayerLessonCtrl.ts` | `isExchangeHandledByNtf()` 方法 |
| `CMNewPlayerLessonCtrl.ts` | `initGameCenterForLesson()` — 如果不再需要外部入口 |
| `CMNewPlayerLessonDef.ts` | 删除的枚举值 |

---

## 执行顺序

| 阶段 | 依赖 | 风险 | 验证方式 |
|------|------|------|---------|
| **0** 提取 LessonAction 管道 | 无 | 低 | GameConnect 不再 import lesson 模块 |
| **1** 直调 ntf/rsp Handler | 0 | 中 | 所有 ntf 消息正确抵达 handler |
| **2** WaitForAll 重构 | 0 | 中 | 换三张/定缺阶段计数正确 |
| **3** 出牌 rsp/ntf 分离 | 1 | 中 | 出牌阶段消息类型正确 |
| **4** 碰杠胡序列 | 1 | 低 | 按需执行，不影响现有流程 |
| **5** 玩家等待机制 | 0 | 中 | 玩家出牌等待正常，AI 出牌自动 |
| **6** GameConnect 剥离 | 0 | 低 | 无 getLessonCtrl 引用 |
| **7** CUSTOM 清理 | 1,3 | 低 | 无遗漏的 CUSTOM 分支 |
| **8** 代码清理 | 全部 | 低 | 编译通过，运行正常 |

## 总改动文件清单

| 文件 | 阶段 | 改动量估计 |
|------|------|-----------|
| `game/scripts/lesson/CMNewPlayerLessonCtrl.ts` | 0,1,2,3,5,7,8 | 大量改动 |
| `game/scripts/lesson/CMNewPlayerLessonDef.ts` | 1,2,7,8 | 中等改动 |
| `game/scripts/lesson/CMNewPlayerLessonData.ts` | 1,2,3,4,7 | 中等改动 |
| `game/scripts/network/GameConnect.ts` | 0 | 少量改动（删除拦截代码+加事件） |
| `game/scripts/network/GameConnect.ts` | 6 | 少量改动（事件钩子替换拦截） |

## 不涉及的文件

以下文件在本次重构中不需要修改：
- `Game.ts` — 教程启动逻辑不变
- `GameInfo.ts` — 教程相关接口不变
- `HallPlugin.ts` — 教程状态管理不变
- `GamePlugin.ts` — 教程启动注册不变
- `LessonCtrlRegistry.ts` — 注册逻辑不变
- `ResultManager.ts` — 结算拦截逻辑不变
