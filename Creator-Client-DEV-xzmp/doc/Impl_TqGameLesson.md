# Impl: 新手教程对局实现指导

基于 Proto + BDD 的具体代码变更。每个改动点精确到文件路径。

---

## Step 1: CP 端 — convert 扩展

### 1.1 决策

不新建独立 CP 插件。convert 服务通过 `OnClientRequest` 处理客户端请求，通过 `OnLogon` 自动标记老玩家：

- `OnClientRequest` 处理 `queryTutorialState` / `claimTutorialReward`
- `OnLogon` 自动标记已有对局记录的老玩家（不发奖励）
- Bit flag 扩展：`MIGRATION_BIT.TQNEWPLAYERLESSON = 0x20`
- 客户端驱动领奖：教程结束时客户端调用 `client_request('convert', cb, { req: 'claimTutorialReward' })`

### 1.2 MIGRATION_BIT + REQ_NAME 扩展

```typescript
const MIGRATION_BIT = {
    TQVIP: 0x01,
    TQMONTHCARD: 0x02,
    TQNEWPLAYERDAILYGIFT: 0x04,
    SCORE_COMPENSATE: 0x08,
    GOLD_COIN: 0x10,
    TQNEWPLAYERLESSON: 0x20,   // NEW: bit 5
    ALL_DONE: 0x3F,             // updated: 63
}

const REQ_NAME = {
    // ... existing ...
    QUERY_TUTORIAL_STATE: 'queryTutorialState',
    CLAIM_TUTORIAL_REWARD: 'claimTutorialReward',
}
```

### 1.3 OnClientRequest 处理

新增 `OnClientRequest` 函数处理客户端请求（参考 `cmdecoration_xzmp.ts:945` 的模式）：

```typescript
async function OnClientRequest(creq: modsvr.client_request, cresp: modsvr.client_response, cxt: modsvr.context) {
    let userid = creq.src.client.userid;
    let req_data = creq.req.data;
    let req_name = req_data['req'];

    if (req_name === REQ_NAME.QUERY_TUTORIAL_STATE) {
        let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
        let config = CommonFuncs.loadConfig();
        let isCompleted = (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0;
        cresp.resp.id = 1;
        cresp.resp.data = {
            isCompleted,
            rewardGold: isCompleted ? (config.newPlayerLessonReward ?? 0) : 0
        };
    } else if (req_name === REQ_NAME.CLAIM_TUTORIAL_REWARD) {
        let result = await Business.async_claimTutorialReward(cxt, userid);
        cresp.resp.id = result.success ? 1 : 0;
        cresp.resp.data = {
            success: result.success,
            rewardGold: result.rewardGold
        };
    }
```

### 1.4 Business.async_claimTutorialReward

```typescript
namespace Business {
    export async function async_claimTutorialReward(
        cxt: modsvr.context, userid: number
    ): Promise<{ success: boolean; rewardGold: number }> {
        let config = CommonFuncs.loadConfig();
        if (config.isenable == 0) return { success: false, rewardGold: 0 };

        let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
        let rewardGold = config.newPlayerLessonReward ?? 0;

        // 1. 先发奖励（失败不影响标记）
        let rewardOk = true;
        if (rewardGold > 0) {
            rewardOk = await Business.async_sendGoldCoin_internal(cxt, userid, rewardGold);
        }

        // 2. 设 bit（无论发奖结果）
        let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
        await CommonFuncs.async_setMigrationFlags(cxt, userid, newFlags);

        return { success: rewardOk, rewardGold };
    }

    export async function async_sendGoldCoin_internal(
        cxt: modsvr.context, userid: number, amount: number
    ): Promise<boolean> {
        // OnClientRequest 上下文中使用 modsvr 发奖能力（需确认具体接口）
        // 参考 CommonFuncs.async_batch_send_reward 需要 src 参数
        // 在 OnClientRequest 中可通过 creq.src 获取
        return true; // placeholder — 取决于 modsvr 框架能力
    }
}
```

### 1.5 OnLogon 自动标记

在 gold coin migration 之后（line ~172）：

```typescript
// tutorial — 已有对局记录的老玩家自动标记
if ((flags & MIGRATION_BIT.TQNEWPLAYERLESSON) === 0) {
    let bout = (logon as any).usergameinfo?.bout ?? 0;
    if (bout > 0) {
        flags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
    }
}

// final flags write
result.flags = flags;
result.newPlayerLesson = {
    isCompleted: (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0,
    rewardGold: config.newPlayerLessonReward ?? 0,
};
CommonFuncs.notifyClient(src, cxt, userid, REQ_NAME.MIGRATION_RESULT, result);
```

### 1.6 convert_xzmp.jsonc 配置

```jsonc
{
    "isenable": 1,
    "guid": "convert_xzmp",
    "newPlayerLessonReward": 100000
}
```

---

## Step 2: 客户端 — HallDefine.ts (Define.ts)

**文件**: `plugins/hall/scripts/Define.ts`

说明：migrationResult 推送中新增 `newPlayerLesson` 字段（含 `isCompleted` / `rewardGold`），
HallPlugin 的 `handleMigrationResult` 直接按该字段名读取，无需新增常量。

---

## Step 3: 客户端 — HallPlugin.ts

**文件**: `plugins/hall/scripts/HallPlugin.ts`

### 3.1 handleMigrationResult 扩展 (line ~113)

```typescript
private handleMigrationResult(data: {
    flags?: number
    levelInfo?: any
    monthCardInfo?: any
    giftInfo?: any
    newPlayerLesson?: {           // 新增
        isCompleted: boolean
        rewardGold: number
    }
}) {
    // ... 既有 leveldefine / monthcard / gift 查询 ...

    // 新增：更新教程状态
    if (data.newPlayerLesson != null) {
        // 写入 CMNewPlayerLesson 的 DataCenter
        let lessonPlugin = ct.centerCtrl.getPlugin('CMNewPlayerLessonPlugin')
        if (lessonPlugin) {
            lessonPlugin.updateState(data.newPlayerLesson)
        }
    }
}
```

> 注：nBout 由客户端本地缓存提供（`ct.LocalCache.getInt("userbout")`），CP 不推送。

### 3.2 onInit 中为 DataCenter 初始化默认教程状态

在 `onInit()` 末尾（~line 80）新增：

```typescript
onInit() {
    // ... 已有逻辑 ...

    // 初始化教程状态默认值
    ct.centerCtrl.addDataToPlugin('CMNewPlayerLessonPlugin', {
        [CMNewPlayerLessonDef.DataType.LessonState]: { isCompleted: false, rewardGold: 0 }
    })
}
```

---

## Step 4: 新增 — CMNewPlayerLesson 插件 (3 个文件)

### 4.1 目录

```
plugins/cmnewplayerlesson/scripts/
├── CMNewPlayerLessonDef.ts
├── CMNewPlayerLessonHelp.ts
└── CMNewPlayerLessonPlugin.ts
```

### 4.2 CMNewPlayerLessonDef.ts

```typescript
export namespace CMNewPlayerLessonDef {
    export const PluginName = 'CMNewPlayerLessonPlugin'

    export const DataType = {
        LessonState: "CMNewPlayerLesson_LessonState",
    }

    export const ReduceType = {
        UpdateLessonState: "CMNewPlayerLesson_UpdateLessonState",
    }

    export interface LessonState {
        isCompleted: boolean
        rewardGold: number
    }
}
```

### 4.3 CMNewPlayerLessonPlugin.ts

```typescript
@ct.plugin
export class CMNewPlayerLessonPlugin extends ct.BasePlugin {
    onInit() {
        return new Promise<void>((resolve) => {
            this.dispatch({
                type: CMNewPlayerLessonDef.ReduceType.UpdateLessonState,
                value: { isCompleted: false, rewardGold: 0 }
            })
            resolve()
        })
    }

    onDataReducer(state: ct.StateRead, action: ct.AnyAction) {
        if (!state) {
            return {
                [CMNewPlayerLessonDef.DataType.LessonState]: { isCompleted: false, rewardGold: 0 }
            }
        }
        switch (action.type) {
            case CMNewPlayerLessonDef.ReduceType.UpdateLessonState:
                return { ...state, [CMNewPlayerLessonDef.DataType.LessonState]: action.value }
        }
        return state
    }

    // 提供外部调用的更新方法
    updateState(state: { isCompleted: boolean, rewardGold: number }) {
        this.dispatch({
            type: CMNewPlayerLessonDef.ReduceType.UpdateLessonState,
            value: state
        })
    }
}
```

### 4.4 CMNewPlayerLessonHelp.ts

```typescript
@ccclass('CMNewPlayerLessonHelp')
export class CMNewPlayerLessonHelp extends ct.BaseFunctionNode {
    static isCompleted(): boolean {
        let state = this.dataCenter.getState(CMNewPlayerLessonDef.PluginName)
        return state?.get(CMNewPlayerLessonDef.DataType.LessonState)?.isCompleted || false
    }

    static getRewardGold(): number {
        let state = this.dataCenter.getState(CMNewPlayerLessonDef.PluginName)
        return state?.get(CMNewPlayerLessonDef.DataType.LessonState)?.rewardGold || 0
    }

    static isNewPlayer(): boolean {
        if (this.isCompleted()) return false
        let nBout = ct.LocalCache.getInt("userbout", 0)
        return nBout <= 0
    }
}
```

---

## Step 5: 客户端 — GameInfo.ts

**文件**: `game/scripts/GameInfo.ts`

新增三个静态方法（建议放在文件顶部，`GamePlugin` import 之后，~line 18-19 后）：

```typescript
// 检查是否需要新手教程
static checkNeedLesson(): boolean {
    return CMNewPlayerLessonHelp.isNewPlayer()
}

// 检查是否处于教程对局中
static isLessonPlaying(): boolean {
    return window["_isLessonPlaying"] === true
}

// 请求 CP 发奖并标记教程完成
// 由 Game.ts 在教程对局结束时调用
static requestClaimTutorialReward(callback: (success: boolean, rewardGold: number) => void) {
    ct.CommonCPInterFace.client_request('convert', (res: any) => {
        if (res && res.data && res.id === 1) {
            // 更新 DataCenter 教程状态
            let plugin = ct.centerCtrl.getPlugin('CMNewPlayerLessonPlugin')
            if (plugin) {
                plugin.updateState({
                    isCompleted: true,
                    rewardGold: res.data.rewardGold
                })
            }
            callback(res.data.success, res.data.rewardGold)
        } else {
            callback(false, 0)
        }
    }, { req: 'claimTutorialReward' })
}
```

> 注意：发奖由客户端驱动。教程对局结束时，Game.ts 调用 `GameInfo.requestClaimTutorialReward()`，
> 通过 `client_request('convert', cb, { req: 'claimTutorialReward' })` 请求 CP 发奖和标记。
> CP 的 `OnClientRequest` 处理设 bit + 发金币，返回结果后客户端更新 DataCenter 并跳转到真实房间。

---

## Step 6: 新增 — Action_FindSuitableRoom

**文件**: `plugins/hall/scripts/actions/action_findsuitableroom.ts`

参考 `action_getsuitableroomid.ts` 的结构，新建文件：

```typescript
@ct.action({name:"Action_FindSuitableRoom"})
export class Action_FindSuitableRoom extends ct.BTAction {
    status = ct.b3.RUNNING

    open(tick: ct.Tick): void {
        // 1. 检查是否需要新手教程
        if (CMNewPlayerLessonHelp.isNewPlayer()) {
            let singlePlayerCfg = ct.additionConfig.getFunction("singleplayer")
            let roomId = singlePlayerCfg?.roomId
            if (roomId) {
                this.setOutputData({ roomId })
                this.status = ct.b3.SUCCESS
                return
            }
        }

        // 2. 正常房间查找（合并 BaseLayer/SecondLayer 逻辑）
        let roomId = this.findSuitableRoomId()
        this.setOutputData({ roomId })
        this.status = ct.b3.SUCCESS
    }

    tick(tick) {
        return this.status
    }

    private findSuitableRoomId(): number {
        // 从 this.dataCenter 读取财富信息
        // 复制 BaseLayer.ts:868-891 的 findRoom2 + findRoom 逻辑
        // ...
    }

    // findRoom2 / findRoom / getBalancedRoomByRoom 方法
    // 从 BaseLayer.ts:916+ 复制
}
```

---

## Step 7: 改造入口文件 (4 处)

### 7.1 RoomNode.ts:131-149

**文件**: `plugins/hall/scripts/components/RoomNode.ts`

替换 `onClick()` 中的 `isSinglePlayer` 分支和 `KEY_SYSGAME` 分支：

```typescript
onClick() {
    // ... 前面的版本检查、subgame 检查、gameClickRoomCB ...

    // 替换点：line 131-149 全部替换为：
    // 使用 Action_FindSuitableRoom 获取目标房间
    let action = ct.btreeCenter.createAction("Action_FindSuitableRoom")
    if (action) {
        // 同步执行或通过 btreeCenter.runAction
        // 实际调用方式根据 ct.BTAction 的运行模式决定
        // 简化方案：直接使用 CMNewPlayerLessonHelp 判断
        if (CMNewPlayerLessonHelp.isNewPlayer()) {
            let cfg = ct.additionConfig.getFunction("singleplayer")
            if (cfg?.roomId) {
                ct.startGame(cfg.roomId, ct.StartGameSource.kSourceClickRoom)
                return
            }
        }
    }

    // 原正常流程
    let isSinglePlayer = ct.hallCenter.isSinglePlayerRoom(ct.hallCenter.getRoom(this.roomId))
    if (isSinglePlayer && !ct.hallCenter.isInSubgame()) {
        ct.startGame(this.roomId, ct.StartGameSource.kSourceClickRoom)
    } else {
        // ... 正常网络检查
    }
}
```

### 7.2 AreaNode.ts:177-182

**文件**: `plugins/hall/scripts/components/AreaNode.ts`

替换 `KEY_SYSGAME` 分支：

```typescript
// 原有：
// let roomList = ct.hallCenter.getRoomListByAreaId(ct.additionConfig.getFunction(ct.FunctionKeys.KEY_SYSGAME)?.areaList[0])
// if(roomList && roomList.length > 0 && ...)

// 替换为：
if (CMNewPlayerLessonHelp.isNewPlayer()) {
    let cfg = ct.additionConfig.getFunction("singleplayer")
    if (cfg?.roomId) {
        ct.startGame(cfg.roomId, ct.StartGameSource.kSourceQuickStart)
        return
    }
}
```

### 7.3 BaseLayer.ts:868-891

**文件**: `plugins/hall/scripts/layers/BaseLayer.ts`

`findSuitableRoomId` 方法保留作为 Action 内部的实现，但 `BaseLayer` 自身的调用改为通过 Action。因为 `BaseLayer` 在重构范围内的优先级低于 RoomNode/AreaNode，可以先保留不动，等后续重构。

### 7.4 SecondLayer.ts:318

同理，先保留不动。核心改造点在 RoomNode 和 AreaNode 即可覆盖 90% 的入口场景。

---

## Step 8: 新增 — TqGameLesson + LessonData

### 8.1 TqGameLesson.ts

**文件**: `game/scripts/common/TqGameLesson.ts`

```typescript
export enum MessageType {
    RSP = 1,
    NOTIFY = 2,
    CUSTOM = 3,
}

export interface LessonMessage {
    type: MessageType
    msgID: number
    handler?: string
    data?: any
    delay: number
}

export class TqGameLesson {
    private gameInfo: typeof GameInfo
    private sequence: LessonMessage[]
    private isEnding: boolean = false
    private isPaused: boolean = false
    private resolveNext: (() => void) | null = null

    constructor(gameInfo: typeof GameInfo) {
        this.gameInfo = gameInfo
        this.sequence = LessonData.getSequence()
    }

    async lessonStart(): Promise<void> {
        try {
            for (const msg of this.sequence) {
                if (this.isEnding) break
                await this.delay(msg.delay)
                this.dispatchMessage(msg)
                // 如果消息需要等待玩家操作，暂停
            }
        } catch (err) {
            console.error("TqGameLesson error:", err)
        }
    }

    private dispatchMessage(msg: LessonMessage) {
        switch (msg.type) {
            case MessageType.RSP:
                this.dealRsp(msg.msgID, msg.data)
                break
            case MessageType.NOTIFY:
                this.dealNotify(msg.msgID, msg.data)
                break
            case MessageType.CUSTOM:
                this.dealCustom(msg.msgID)
                break
        }
    }

    private dealRsp(msgID: number, data: any) {
        // 根据 msgID 映射到 GameInfo 的方法调用
        // 示例：EnterGame → GameInfo.ntfGameWin / GameInfo.updatePlayerInfo 等
    }

    private dealNotify(msgID: number, data: any) {
        // 模拟推送消息
    }

    private dealCustom(msgID: number) {
        switch (msgID) {
            case 1: // BETTERCARD
                break
            case 2: // GETREWARD — 教程结束触发 CP 发奖
                this.onLessonReward?.()
                this.lessonOver()
                break
            case 3: // LESSONOVER
                this.lessonOver()
                break
            case 4: // FIRSTHU
                break
            case 5: // CANHUTINGINFO
                break
            case 6: // NOTCALQYS
                break
        }
    }

    // 教程结束时由 Game.ts 注入发奖回调
    public onLessonReward: (() => void) | null = null

    // 玩家操作后调用，推进到下一步
    nextStep() {
        // 暂停模式恢复
    }

    lessonOver() {
        this.isEnding = true
        // Game.ts 在检测到 _isEnding 后调用 claimTutorialReward
    }

    isEnding(): boolean { return this.isEnding }
    setIsEnding(v: boolean) { this.isEnding = v }

    private delay(seconds: number): Promise<void> {
        return new Promise(resolve => setTimeout(resolve, seconds * 1000))
    }
}
```

### 8.2 LessonData.ts

**文件**: `game/scripts/common/LessonData.ts`

骨架：

```typescript
export class LessonData {
    static getSequence(): LessonMessage[] {
        return [
            // 14 个阶段，从 Lua LessonData.lua 逐条移植
            // 每个阶段包含：RSP（模拟包）、NOTIFY（推送）、CUSTOM（控制）
            // delay 控制消息间隔（秒）

            // Stage 1: EnterGame
            { type: MessageType.RSP, msgID: 0x0001, data: {...enterGameData...}, delay: 1.0 },
            // Stage 2: 发牌
            // ...
            // Stage 14: 结算
        ]
    }
}
```

---

## Step 9: Game.ts — 教程启动和结算

**文件**: `game/scripts/components/Game.ts`

### 9.1 新增成员变量（~line 20, class 定义后）

```typescript
private _isLessonPlaying: boolean = false
private _lesson: TqGameLesson | null = null
```

### 9.2 onLoad 中启动（line 38 处）

```typescript
onLoad(): void {
    // ... 既有初始化逻辑 ...

    // 新增：检查教程
    if (GameInfo.checkNeedLesson()) {
        this.startLesson()
    }
}

private startLesson() {
    this._isLessonPlaying = true
    window["_isLessonPlaying"] = true  // 供 GameInfo.isLessonPlaying 读
    this._lesson = new TqGameLesson(GameInfo)
    this._lesson.lessonStart()
}
```

### 9.3 startLesson 注入发奖回调

```typescript
private startLesson() {
    this._isLessonPlaying = true
    window["_isLessonPlaying"] = true
    this._lesson = new TqGameLesson(GameInfo)

    // 注入发奖回调：LessonData 中 CUSTOM GETREWARD 触发此回调
    this._lesson.onLessonReward = () => {
        this.claimTutorialReward()
    }

    this._lesson.lessonStart()
}
```

### 9.4 发奖流程

```typescript
private claimTutorialReward() {
    // 先暂停状态机推进，等待 CP 返回
    GameInfo.requestClaimTutorialReward((success: boolean, rewardGold: number) => {
        // 无论发奖成功与否，都结束教程跳到真实房间
        this.lessonCleanup()
    })
}

private lessonCleanup() {
    this._isLessonPlaying = false
    window["_isLessonPlaying"] = false
    this.lessonRoomSkip()
}
```

### 9.5 roomSkip 方法

```typescript
private lessonRoomSkip() {
    // 通过 Action_FindSuitableRoom 获取真实房间
    // 此时 CMNewPlayerLessonHelp.isNewPlayer() == false（CP 已完成标记）
    let action = ct.btreeCenter.createAction("Action_FindSuitableRoom")
    if (action) {
        // 走 action 逻辑，返回真实房间
    }
    // 备用方案：
    ct.startGame(0, ct.StartGameSource.kSourceQuickStart)
}
```

---

## Step 10: PlayerInfoNode.ts — 头像点击拦截

**文件**: `game/scripts/components/PlayerInfoNode.ts`

查找头像点击事件处理函数（搜索 `onClick` 或 `click` 相关处理），在入口处增加判断：

```typescript
// 在头像点击处理函数的第一行
onAvatarClick() {
    if (window["_isLessonPlaying"]) {
        return  // 教程期间不弹出个人信息
    }
    // ... 原有逻辑 ...
}
```

---

## Step 11: OperateBtnsManager — 按钮约束

**文件**: `game/scripts/manager/OperateBtnsManager.ts`

在按钮显示/隐藏逻辑中增加教程标记检查：

```typescript
// 找到按钮可见性更新的入口函数
private updateBtnsVisibility() {
    if (window["_isLessonPlaying"]) {
        // 只显示当前教程阶段允许的按钮
        this.hideAllBtns()
        // 由 TqGameLesson 控制哪些按钮可见
        return
    }
    // ... 原有逻辑 ...
}
```

---

## 实现顺序

| 步 | 内容 | 变更文件数 | 代码量估计 |
|----|------|-----------|-----------|
| 1 | CP 端 convert 扩展 | 1 (CP 代码) | 小 |
| 2 | CMNewPlayerLesson 插件 | 3 (新建) | ~50 行 |
| 3 | HallPlugin 集成 + Define 常量 | 2 | ~20 行 |
| 4 | GameInfo 新增方法 | 1 | ~15 行 |
| 5 | Action_FindSuitableRoom | 1 (新建) | ~100 行 (含复制逻辑) |
| 6 | RoomNode + AreaNode 入口改造 | 2 | ~20 行 |
| 7 | PlayerInfoNode 头像拦截 | 1 | ~5 行 |
| 8 | TqGameLesson + LessonData | 2 (新建) | ~4000 行 (主要是 LessonData) |
| 9 | Game.ts 集成 | 1 | ~60 行 |
| 10 | OperateBtnsManager 约束 | 1 | ~10 行 |

**推荐启动顺序**：2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 1 (CP 端可由后端并行)
