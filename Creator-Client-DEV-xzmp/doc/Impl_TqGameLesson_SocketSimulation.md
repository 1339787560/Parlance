# Impl: 新手教程 Socket 模拟方案实现指导

> 基于 Proto_TqGameLesson.md 的架构 + BDD 场景，采用 **Socket 消息模拟**方案。
> 与简化版（直接调 GameInfo 方法）不同，本方案将 LessonData 中的消息
> 通过 protobuf/treepack 序列化后，经 `GameSocket.simulateMessage()` 注入，
> 走完整的消息处理器路径（与真实服务端消息处理一致）。

## 一、方案对比

| 方面 | 简化方案（旧 Impl） | Socket 模拟方案（本方案） |
|------|-------------------|------------------------|
| NOTIFY 消息 | 直接调 GameInfo/Manager 方法 | `serialize()` → `simulateMessage()` → 走 socket handler |
| RSP 消息 | 直接调 GameInfo 方法 | `eventCenter.emit(onLessonRsp)` → 监听方处理 |
| CUSTOM 消息 | 控制器内 switch 处理 | 控制器内 switch 处理（不变） |
| 玩家身份 | 硬编码 | `ct.businessUtils` 动态生成 |
| 数据格式 | 简化标记位 | 完整 protobuf/treepack 结构 |
| 维护成本 | 低（改动少） | 中（需对齐序列化格式） |
| 真实度 | 低（不走 handler） | 高（与真实消息路径一致） |
| 可测试性 | 中 | 高（handler 被完整测试） |

## 二、架构总览

```
LessonData (14 stages)
  └─ TqLessonCtrl (setTimeout 调度)
       ├─ NOTIFY → serializeLessonMsg() → GameSocket.simulateMessage()
       │              ├─ protobuf: ct.serializepb(datatbl, "XZMSdef.PB_*") → ArrayBuffer
       │              └─ treepack: ct.serialize(datatbl, "STRUCT_NAME").GetBuffer() → ArrayBuffer
       │
       ├─ RSP → eventCenter.emit(GameEvent.onLessonRsp, {msgID, datatbl})
       │       └─ 监听方按 msgID 处理（含 isLessonEnter 特殊分支）
       │
       └─ CUSTOM → TqLessonCtrl.processCustom()
                    ├─ BETTERCARD → emit onLessonBetterCard
                    ├─ GETREWARD → claimReward() → CP 领奖 → roomSkip()
                    ├─ LESSONOVER → lessonOver()
                    ├─ FIRSTHU → emit onLessonFirstHu
                    ├─ CANHUTINGINFO → emit onLessonCanHuTingInfo
                    └─ NOTCALQYS → 不计缺一色标记
```

## 三、消息序列化映射

serializeLessonMsg() 函数（TqLessonCtrl.ts）将所有 NOTIFY 消息的 datatbl 序列化为 ArrayBuffer：

| msgID | 序列化方式 | 结构名 |
|-------|-----------|--------|
| GR_START_SOLOTABLE (211028) | protobuf | XZMSdef.PB_GAME_START_INFO |
| GR_GAME_START (210200) | protobuf | XZMSdef.PB_GAME_START_INFO |
| GR_PLAYER_ENTER (211029) | treepack | SOLO_PLAYER_COR |
| MJ_GR_CARDS_THROW (222170) | treepack | CARDS_THROW_WITHFAN |
| MJ_GR_CARD_CAUGHT (229160) | treepack | CARD_CAUGHT_MJ |
| GR_SYSTEMMSG (229800) | treepack | SYSTEMMSG |
| GR_EXCHANGE3CARDS_FINISHED (229821) | treepack | EXCHANGE3CARDSINNER |
| GR_AUCTION_FINISHED (222168) | treepack | AUCTION_DINGQUE |
| MJ_GR_CARD_CHI/PENG/GANG (211058-211066) | treepack | COMB_CARD |
| GR_MJ_QUERY_HUINFO (219006) | protobuf | XZMSdef.RspHuInfo |
| GR_MJ_QUERY_TINGINFO (219007) | protobuf | XZMSdef.RspTingInfo |
| GR_PRE_SAVE_RESULT (400106) | protobuf | XZMSdef.PB_PRE_SAVE_RESULT |
| MJ_GR_GAME_WIN (211080) | protobuf | XZMSdef.GAME_WIN_RESULT |
| GR_PLAYING_DEPOSIT_NOT_ENOUGH (400104) | protobuf | XZMSdef.PB_GIVEUP_INFO |
| MJ_GR_PREGANG_OK | treepack | PREGANG_OK |

序列化方式选择规则：
- `ct.serializepb(datatbl, "XZMSdef.PB_*")` — protobuf 消息，返回 ArrayBuffer
- `ct.serialize(datatbl, "STRUCT_NAME").GetBuffer()` — treepack 消息，返回 BinaryStream → ArrayBuffer

## 四、玩家身份动态生成

### 4.1 设计原则

- **玩家保持 chair 3**（与 Lua LessonData 原始录制一致）
- 玩家信息从 `ct.businessUtils` / `GameInfo.dataCenter` 实时获取
- Bot 信息使用固定模板 + 动态 userID
- **不做椅子旋转**（与之前方案的关键区别）

### 4.2 玩家身份

```typescript
function makePlayerIdentity() {
    return {
        nUserID: ct.businessUtils.getUserId(),           // 真实 userID
        szNickName: ct.businessUtils.getNickName?.() || ct.businessUtils.getUserName(),
        szUsername: ct.businessUtils.getUserName(),
        nDeposit: GameInfo.dataCenter.getScore(),        // 真实携带金币
        nScore: 0, nWin: 0, nLoss: 0, nStandOff: 0, nBout: 0, // 全 0
        chairNO: 3,                                      // 与 Lua 一致
    };
}
```

### 4.3 Bot 身份

```typescript
// 固定配置
bots = [
    { name: "test001", deposit: 70000, score: 70000 },  // chair 0
    { name: "test002", deposit: 20000, score: 20000 },  // chair 1
    { name: "test003", deposit: 70000, score: 70000 },  // chair 2
];

// userID = 玩家 userID + index（确保不与真实玩家冲突）
bot.nUserID = playerId + index;   // +1, +2, +3
```

### 4.4 userID 映射

Lua 原始数据的 userID 是硬编码的（733810~733813），需要映射到动态 ID：

```typescript
// 旧 ID → 新 ID
buildIdMap(playerId) = [
    733811 → playerId + 1,   // chair 0 bot (test001)
    733813 → playerId + 2,   // chair 1 bot (test002)
    733812 → playerId + 3,   // chair 2 bot (test003)
    733810 → playerId,       // chair 3 玩家
];
```

`transformDatatbl()` 递归遍历 datatbl 对象树，替换所有 `nUserID`、`nChairNO`、`nSendChair`、`nNextChair`、`nFangCardChairNO`、`nSendUser` 字段。

**注意**：本方案只替换 userID，不旋转 chairNO。Lua 原始数据中玩家已在 chair 3，保持不变。

## 五、LessonData 模板数据

### 5.1 文件位置

`game/scripts/lesson/TqLessonData.ts`

### 5.2 数据组织

```
14 stages, 每个 stage 包含若干 LessonMessage:

Stage 0 (index 0): 进入游戏
  ├─ RSP 210200 — 进入游戏响应（含玩家信息、soloplayer 数据）
  ├─ RSP GR_GET_MAX_FAN — 最大番数
  └─ NOTIFY GR_PLAYER_ENTER × 3 — bot 玩家进场（chair 0,1,2）

Stage 1 (index 1): GR_START_SOLOTABLE
  ├─ NOTIFY 211028 — soloTable + soloPlayers + 手牌数据（nChairCards）
  └─ NOTIFY GR_PRE_SAVE_RESULT — 初始结算快照

Stage 2: 换牌阶段系统消息（SYSTEMMSG × 3）

Stage 3: 执行换三张
  ├─ RSP GR_EXCHANGE_CARDS — 客户端处理换牌请求
  ├─ NOTIFY GR_SYSTEMMSG — 换牌系统消息
  └─ NOTIFY GR_EXCHANGE3CARDS_FINISHED — 换牌完成

Stage 4: 定缺通知（SYSTEMMSG × 3）

Stage 5: 定缺完成 + 听牌信息
  ├─ NOTIFY GR_SYSTEMMSG — 定缺确认
  ├─ NOTIFY GR_AUCTION_FINISHED — 定缺结果
  └─ NOTIFY GR_MJ_QUERY_TINGINFO — 听牌提示

Stage 6: 出牌轮
  ├─ RSP MJ_GR_THROW_CARDS — 玩家出牌请求
  ├─ NOTIFY GR_MJ_QUERY_HUINFO — 胡牌信息
  ├─ NOTIFY MJ_GR_CARD_CAUGHT × 3 — 摸牌
  └─ NOTIFY MJ_GR_CARDS_THROW × 3 — 出牌

Stage 7: 听牌提示
  ├─ CUSTOM NOTCALQYS — 不计缺一色
  ├─ NOTIFY GR_MJ_QUERY_TINGINFO — 听牌详情
  └─ CUSTOM BETTERCARD — 选更好的牌

Stage 8: 玩家出牌轮
  ├─ RSP MJ_GR_THROW_CARDS
  ├─ NOTIFY GR_MJ_QUERY_HUINFO
  ├─ NOTIFY MJ_GR_CARD_CAUGHT × 3
  └─ NOTIFY MJ_GR_CARDS_THROW × 3

Stage 9~10: 出牌轮（同上模式）
Stage 11: 金币不足
  ├─ NOTIFY GR_PLAYING_DEPOSIT_NOT_ENOUGH — chair 2 出局
  └─ NOTIFY GR_SYSTEMMSG — 出局系统消息
Stage 12: 出牌轮
Stage 13: 结算
  ├─ NOTIFY GR_PLAYING_DEPOSIT_NOT_ENOUGH — chair 1 出局
  ├─ NOTIFY MJ_GR_GAME_WIN — 胡牌结算
  ├─ CUSTOM GETREWARD — 领取奖励
  └─ CUSTOM LESSONOVER — 教程结束
```

## 六、TqLessonCtrl 控制器

### 6.1 文件位置

`game/scripts/lesson/TqLessonCtrl.ts`

### 6.2 单例模式

```typescript
export class TqLessonCtrl extends ct.BaseViewCtrl {
    private static _instance: TqLessonCtrl = null;

    static getInstance(): TqLessonCtrl {
        if (!TqLessonCtrl._instance) {
            TqLessonCtrl._instance = new TqLessonCtrl();
        }
        return TqLessonCtrl._instance;
    }
}
```

### 6.3 核心状态

| 字段 | 类型 | 说明 |
|------|------|------|
| `_lessonStep` | LessonStatus | 当前教程步骤 |
| `_isEnding` | boolean | 是否已结束 |
| `_curStageIndex` | number | 当前阶段索引 |
| `_curMsgIndex` | number | 当前阶段内的消息索引 |
| `_running` | boolean | 是否正在运行 |
| `_roomInfo` | any | 当前房间信息（用于 isNeedLesson） |
| `_timeoutIds` | number[] | 待清除的 setTimeout ID |

### 6.4 生命周期

```
lessonStart()
  → _running = true, _isEnding = false
  → emit onLessonStart
  → dispatchCurrentMessage()  // setTimeout 派发第一条消息

processMessage(msg)
  ├─ msgType == NOTIFY → serializeLessonMsg() → simulateMessage() → nextStep()
  ├─ msgType == RSP → injectRsp() → eventCenter.emit(onLessonRsp) → nextStep()
  └─ msgType == CUSTOM → processCustom() → 本地处理

nextStep()
  → _curMsgIndex++
  → 若阶段结束: _curStageIndex++, _curMsgIndex = 0
  → 若所有阶段完成: lessonOver()
  → 否则: dispatchCurrentMessage()

lessonOver()
  → _running = false, setIsEnding(true)
  → claimReward() → CP 领奖 → roomSkip()
```

### 6.5 消息处理细节

**NOTIFY 消息处理**：

```typescript
private injectNotify(msgID: number, datatbl: any) {
    let buffer = serializeLessonMsg(msgID, datatbl);
    let socket = ct.mjGameCenter?.socket;
    if (socket && typeof (socket as any).simulateMessage === 'function') {
        (socket as any).simulateMessage(msgID, buffer);
    }
}
```

**RSP 消息处理**：

```typescript
private injectRsp(msgID: number, datatbl: any) {
    if (datatbl?.isLessonEnter) {
        // 进入游戏 RSP：设置玩家身份数据
        let player = datatbl.player;
        if (player) {
            ct.hallCenter.setEnterRoomPlayerData(player);
        }
        return;
    }
    // 其他 RSP：通过事件分发
    eventCenter.emit(GameEvent.onLessonRsp, { msgID, datatbl });
}
```

**CUSTOM 消息处理**：

| ID | 名称 | 处理 |
|----|------|------|
| 1 | BETTERCARD | emit onLessonBetterCard，提示选更好的牌 |
| 2 | GETREWARD | emit onLessonGetReward，触发领奖流程 |
| 3 | LESSONOVER | 直接 lessonOver() |
| 4 | FIRSTHU | emit onLessonFirstHu，首次胡牌处理 |
| 5 | CANHUTINGINFO | emit onLessonCanHuTingInfo，提示可胡 |
| 6 | NOTCALQYS | 不计缺一色标记 |

## 七、GameSocket 扩展

### 7.1 文件位置

`game/scripts/override/GameSocket.ts`

### 7.2 改动

新增 `simulateMessage()` 方法和 `addHandler()` 重写：

```typescript
export class GameSocket extends ct.Socket {
    private _msgHandlers: Map<number, Function> = new Map()

    // 重写：记录 handler 到本地 map
    addHandler(respondID: number, callback: Function, target?: unknown) {
        this._msgHandlers.set(respondID, callback);
        return super.addHandler(respondID, callback, target);
    }

    // 本地注入消息：直接调用已注册的 handler
    simulateMessage(respondID: number, body: ArrayBuffer) {
        let handler = this._msgHandlers.get(respondID);
        if (handler) {
            handler(body);
        }
    }
}
```

## 八、集成点

### 8.1 教程启动 — GamePlugin

**文件**: `game/scripts/GamePlugin.ts`

在 `event_onGameEnterOK` 中：

```typescript
// 进入游戏后检查是否需要启动教程
let lessonCtl = TqLessonCtrl.getInstance();
let tableInfo = (GameInfo as any).tableInfo;
if (tableInfo) {
    lessonCtl.setCurRoomInfo({ nRoomID: tableInfo.ei?.nRoomID || tableInfo.nRoomID });
}
if (lessonCtl.isNeedLesson()) {
    lessonCtl.lessonStart();
}
```

### 8.2 结算拦截 — ResultManager

**文件**: `game/scripts/manager/ResultManager.ts`

```typescript
showResult() {
    let lessonCtl = TqLessonCtrl.getInstance();
    if (lessonCtl && lessonCtl.isEnding()) {
        lessonCtl.roomSkip();  // 跳过结算 UI，直接跳转
        return;
    }
    // ... 正常结算流程 ...
}
```

### 8.3 GR_EXCHANGE_CARDS RSP 处理

Stage 3 包含 `GR_EXCHANGE_CARDS RSP`（`datatbl: {}`）。此消息通过 `eventCenter.emit(onLessonRsp)` 分发。需要有一个监听方处理此消息，调用摸牌/换牌逻辑。

推荐做法：在游戏框架的初始监听注册中，增加对 `onLessonRsp` 的处理：

```typescript
eventCenter.on(GameEvent.onLessonRsp, (data: { msgID: number, datatbl: any }) => {
    if (data.msgID === GameReqDef.GR_EXCHANGE_CARDS) {
        // 触发客户端换牌逻辑
        // 例如: GameInfo.sendExchangeCards()
    }
    if (data.msgID === GameReqDef.MJ_GR_THROW_CARDS) {
        // 触发客户端出牌逻辑（让玩家可以出牌）
    }
});
```

## 九、TqLessonCtrl 实现步骤

### Step 1: TqLessonDef.ts — 类型定义

创建枚举和接口：
- `LessonMsgType` (RSP=1, NOTIFY=2, CUSTOM=3)
- `CUSTOM_ID` (BETTERCARD=1, GETREWARD=2, LESSONOVER=3, FIRSTHU=4, CANHUTINGINFO=5, NOTCALQYS=6)
- `LessonStatus` (NONE=0, INTRODUCE=1, ... HUCARD=9)
- `LessonMessage` 接口 (msgID, msgType, delay, datatbl)
- `LessonStage` 接口 (messages[])
- `TutorialState` 接口 (isCompleted, rewardGold)

### Step 2: GameSocket.ts — 添加 simulateMessage

重写 `addHandler` + 新增 `simulateMessage` 方法。

### Step 3: TqLessonCtrl.ts — 控制器实现

- 单例模式
- 生命周期方法: lessonStart, nextStep, lessonOver, reset
- 消息分发: dispatchCurrentMessage, processMessage
- NOTIFY 注入: injectNotify → serializeLessonMsg → simulateMessage
- RSP 注入: injectRsp → eventCenter.emit
- CUSTOM 处理: processCustom → switch
- serializeLessonMsg 函数: msgID → 序列化方式映射

### Step 4: TqLessonData.ts — 数据构建（最重要的部分）

- `buildLessonStages()` — 统一构建入口，调用所有子函数
- `makePlayerIdentity()` — 从 ct.businessUtils 生成玩家身份
- `makeBotIdentity(index, playerId)` — 生成 bot 身份（test001~test003）
- `buildIdMap(playerId)` — 旧 userID → 新 userID 映射
- `transformDatatbl(dt, idMap)` — 递归替换 datatbl 中的 userID
- `templateStage0()` — 构建 stage 0（进入游戏）
- `buildSoloPlayer()` — 构建 soloPlayers 数组（GR_START_SOLOTABLE）
- `rawStageData()` — 原始模板数据（stages 1~13，含旧 userID）
- 缓存: `_stages` 懒加载

### Step 5: 集成 — GamePlugin + ResultManager

- GamePlugin: event_onGameEnterOK 中启动教程
- ResultManager: showResult 中拦截 isEnding

## 十、文件变更清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `game/scripts/lesson/TqLessonDef.ts` | 常量、枚举、消息类型定义 |
| `game/scripts/lesson/TqLessonCtrl.ts` | 教程控制器单例 |
| `game/scripts/lesson/TqLessonData.ts` | 14 阶段教程数据 + 动态身份生成 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `game/scripts/override/GameSocket.ts` | 新增 `addHandler` 重写 + `simulateMessage` 方法 |
| `game/scripts/GamePlugin.ts` | `event_onGameEnterOK` 中注入教程启动 |
| `game/scripts/manager/ResultManager.ts` | `showResult` 中拦截 `isEnding` => `roomSkip` |
| `game/scripts/event/game-event.ts` | 新增 `onLessonStart` / `onLessonRsp` / `onLessonBetterCard` 等事件常量 |
| `game/scripts/network/GameReqDef.ts` | 确保所需 msgID 常量已定义（如 GR_EXCHANGE_CARDS） |

## 十一、实现顺序

| 步 | 内容 | 文件数 | 验证标准 |
|----|------|--------|---------|
| 1 | TqLessonDef.ts 类型定义 | 1 新建 | 导入无报错 |
| 2 | GameSocket.ts simulateMessage | 1 修改 | simulateMessage 能触发 handler |
| 3 | TqLessonCtrl.ts 控制器骨架 + serializeLessonMsg | 1 新建 | 消息能序列化 |
| 4 | TqLessonData.ts 数据 + 身份生成 | 1 新建 | getLessonStage 返回正确数据 |
| 5 | TqLessonCtrl.ts 完整生命周期 | 1 修改 | 消息能逐条派发 |
| 6 | GamePlugin 集成 + ResultManager 拦截 | 2 修改 | 教程自动启动 |
| 7 | game-event 事件常量 | 1 修改 | 编译通过 |

## 十二、关键注意事项

### 12.1 `setEnterRoomPlayerData` 的调用时机

`ct.hallCenter.setEnterRoomPlayerData(player)` 必须在框架使用 `GameInfo.getMyChairNO()` 之前调用。这个调用位于 `injectRsp` 的 `isLessonEnter` 分支中（stage 0 的 RSP 210200 消息处理时触发）。

### 12.2 soloPlayers 数组顺序与 drawIndex

`ct.gameCenter.setSoloPlayers(soloPlayers)` 根据数组位置分配 drawIndex：
- `soloPlayers[0]` → drawIndex 1
- `soloPlayers[1]` → drawIndex 2
- 以此类推...

`ntfStartSoloTable` handler 中的 `getUserIDByDrawIndex(drawIndex)` 查找玩家 userID，匹配到后设置 `enterPlayerInfo.nChairNO`。

因此 soloPlayers 数组的顺序必须与 nUserIDs、nChairCards 的顺序一致。

### 12.3 Bot userID 一致性

所有消息中的 bot userID 必须一致。`buildIdMap()` 中的映射在所有数据中共用同一个 `idMap`，由 `buildLessonStages()` 统一创建并传递给 `transformDatatbl()`。

### 12.4 延迟计算

`msg.delay` 以秒为单位，在 `dispatchCurrentMessage` 中乘以 1000 转为毫秒传给 `setTimeout`：

```typescript
let delay = (msg.delay != null ? msg.delay : 0) * 1000;
```

### 12.5 资源清理

`reset()` 和 `lessonOver()` 都调用 `clearAllTimeouts()` 防止教程结束后仍有待执行的回调。在 GamePlugin 的 `onDestroy` 或场景切换时也需要调用 `reset()`。
