# Proto: 新手教程对局 (TqGameLesson) Creator 迁移设计

> 将 Lua 版 TqGameLesson 客户端模拟对局迁移到 Creator 客户端。
> 状态存储由 CP（cmnewplayerlesson）管理，对局行为由客户端控制。

---

## 1. 概述

### 1.1 目标

- 为 Creator 客户端实现新手教学对局功能
- 新玩家（nBout == 0）进入"单机房"进行 guided 对局
- 完成教程后，发放真实金币奖励，跳转到真实房间

### 1.2 架构策略

直接移植 Lua 行为 + adapter 适配 Creator 环境（非服务端驱动）。

### 1.3 术语

| 术语 | 含义 |
|------|------|
| CMNewPlayerLesson | 客户端插件，管理教程完成状态 |
| TqGameLesson | 客户端纯逻辑模块，模拟对局状态机 |
| LessonData | 14 阶段 3500+ 行预定义消息序列 |
| singleplayer | additionConfig 中配置的单机房间 |
| roomSkip | 教程结束后跳转到真实房间 |
| convert | CP 服务，通过 OnClientRequest 和 OnLogon 管理教程状态 |

---

## 2. 架构总览

```
+-- CP convert (OnClientRequest + OnLogon) ---+
|   Bit flag TQNEWPLAYERLESSON 管理            |
|   OnLogon 自动标记老玩家（nBout > 0）        |
|   OnClientRequest: queryTutorialState        |
|                 claimTutorialReward          |
+---------------------------------------------+
          | migrationResult push
          v
+-- HallPlugin ------------------------------+
|   CMNewPlayerLesson DataCenter 托管         |
|   收到 newPlayerLesson 写入 DataCenter       |
+--------------------------------------------+
          |
          | this.dataCenter.getState()
          v
+-- GameInfo --------------------------------+
|   取 CMNewPlayerLesson 数据项               |
|   claimTutorialReward → convert 发奖 + 标记 |
+--------------------------------------------+
          |
          | 持有实例引用
          v
+-- TqGameLesson (纯模块) --------------------+
|   async/await 驱动的 LessonData 状态机       |
|   直接调用 GameInfo 方法注入模拟消息          |
|   CUSTOM 控制消息自处理                      |
+--------------------------------------------+
          |
          | onLoad() 检查启动
          v
+-- Game.ts ---------------------------------+
|   onLoad() → isNeedLesson() → lessonStart() |
|   CUSTOM GETREWARD → claimTutorialReward   |
+--------------------------------------------+
```

### 2.1 组件职责

| 组件 | 类型 | 位置 | 职责 |
|------|------|------|------|
| convert (CP) | 服务端 | `convert_xzmp.ts` | OnLogon 标记、OnClientRequest 处理请求 |
| CMNewPlayerLessonPlugin | 客户端插件 | `plugins/cmnewplayerlesson/` | DataCenter 数据托管 |
| CMNewPlayerLessonHelp | Help 类 | `plugins/cmnewplayerlesson/` | 静态数据访问方法 |
| TqGameLesson | 纯模块 | `game/scripts/common/TqGameLesson.ts` | 模拟对局状态机 |
| LessonData | 数据文件 | `game/scripts/common/LessonData.ts` | 14 阶段预定义消息 |
| Action_FindRoom | BT Action | `plugins/hall/scripts/actions/` | 统一房间查找 |
| GameInfo | 数据管理 | `game/scripts/GameInfo.ts` | 数据访问 + CP 请求 |
| Game | 主控制器 | `game/scripts/components/Game.ts` | 启动守卫 |

---

## 3. CP 扩展: convert

教程状态不由独立 CP 插件管理，而是扩展已有 convert 服务。

### 3.1 CP 侧新增内容

```typescript
// 1. MIGRATION_BIT 扩展
const MIGRATION_BIT = {
    // ... 已有位 ...
    TQNEWPLAYERLESSON: 0x20,   // bit 5 — 新增
    ALL_DONE: 0x3F,             // 63
}

// 2. REQ_NAME 扩展
const REQ_NAME = {
    // ... 已有 ...
    QUERY_TUTORIAL_STATE: 'queryTutorialState',
    CLAIM_TUTORIAL_REWARD: 'claimTutorialReward',
}

// 3. OnClientRequest 处理
// queryTutorialState → 读 bit flag 返回 isCompleted + rewardGold
// claimTutorialReward → 发金币 + 设 bit，返回 success + rewardGold

// 4. OnLogon 自动标记
// 检测 nBout > 0 && bit 未设 → 自动置位（不发奖励）
// 推送 migrationResult 携带 newPlayerLesson.isCompleted

// 5. config 新增
// newPlayerLessonReward: 100000
```

### 3.2 客户端插件: CMNewPlayerLesson

客户端插件负责 DataCenter 托管，不直接和 CP 通信。

```
plugins/cmnewplayerlesson/
├── scripts/
│   ├── CMNewPlayerLessonDef.ts      # 常量、数据类型
│   ├── CMNewPlayerLessonHelp.ts     # 静态 Helper (extend ct.BaseFunctionNode)
│   └── CMNewPlayerLessonPlugin.ts   # 插件类 (extend ct.BasePlugin)
```

### 3.3 数据定义 (CMNewPlayerLessonDef)

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

### 3.4 插件类 (CMNewPlayerLessonPlugin)

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
            return { [CMNewPlayerLessonDef.DataType.LessonState]: { isCompleted: false, rewardGold: 0 } }
        }
        switch (action.type) {
            case CMNewPlayerLessonDef.ReduceType.UpdateLessonState:
                return { ...state, [CMNewPlayerLessonDef.DataType.LessonState]: action.value }
        }
        return state
    }

    updateState(state: { isCompleted: boolean, rewardGold: number }) {
        this.dispatch({
            type: CMNewPlayerLessonDef.ReduceType.UpdateLessonState,
            value: state
        })
    }
}
```

### 3.5 数据访问 (CMNewPlayerLessonHelp)

```typescript
@ccclass('CMNewPlayerLessonHelp')
export class CMNewPlayerLessonHelp extends ct.BaseFunctionNode {
    static isCompleted(): boolean {
        let state = this.dataCenter.getState(CMNewPlayerLessonDef.PluginName)
        return state?.get(CMNewPlayerLessonDef.DataType.LessonState)?.isCompleted || false
    }

    static isNewPlayer(): boolean {
        if (this.isCompleted()) return false
        let nBout = ct.LocalCache.getInt("userbout", 0)
        return nBout <= 0
    }
}
```

### 3.6 CP 接口协议

| 请求 | req 值 | 目标 | 返回值 |
|------|--------|------|--------|
| 查询状态 | `queryTutorialState` | convert OnClientRequest | `{ isCompleted: boolean, rewardGold: number }` |
| 标记+领奖 | `claimTutorialReward` | convert OnClientRequest | `{ success: boolean, rewardGold: number }` |

- 客户端通过 `ct.CommonCPInterFace.client_request('convert', cb, { req: 'queryTutorialState' })` 调用
- 状态通过 `MIGRATION_BIT.TQNEWPLAYERLESSON`（bit 5）位存储
- `OnLogon` 自动标记 nBout > 0 的老玩家（不发奖励）
- 奖励在 `claimTutorialReward` 时由 convert 发金币 + 设 bit（幂等）

---

## 4. 大厅集成 (HallPlugin)

### 4.1 数据托管

教程状态由 convert 的 `OnLogon` 自动推送。HallPlugin 在 `handleMigrationResult` 中收到直接更新：

```typescript
handleMigrationResult(data) {
    // ... 既有 migration 处理 ...

    // 新增：更新教程状态（由 convert OnLogon 推送）
    if (data.newPlayerLesson != null) {
        let lessonPlugin = ct.centerCtrl.getPlugin('CMNewPlayerLessonPlugin')
        if (lessonPlugin) {
            lessonPlugin.updateState(data.newPlayerLesson)
        }
    }
}
```

### 4.2 迁移处理

CP 端的 `OnLogon` 负责自动标记老玩家，客户端不做任何请求：

```
OnLogon 流程：
  → 读取 MIGRATION_BIT（已有）
  → 检测 logon.usergameinfo.bout
  → 若 nBout > 0 且 bit 未设 → 自动标记 bit 5（不发奖励）
  → 推送 migrationResult_convert_xzmp
    → 携带 newPlayerLesson: { isCompleted, rewardGold }
  → HallPlugin.handleMigrationResult 收到后写入 DataCenter
```

### 4.3 首次引导 (FirstLayer)

Creator 客户端 FirstLayer.ts 已有 `updateGuide()`，逻辑与 Lua 版几乎一致：

- 检查 `nBout > 0` → 不显示引导
- 使用 `prefabGuide` 在默认区域/房间上方显示手指动画

不需要改动，已天然适配。

---

## 5. 统一房间查找 Action

### 5.1 现状问题

`findSuitableRoomId` 在多处散布且有重复实现：

| 文件 | 行号 |
|------|------|
| `BaseLayer.ts` | 868 |
| `SecondLayer.ts` | 318 |
| `RMRoomList.ts` | 302 |

已有 `Action_GetSuitableRoomId`（rulesmake 插件），但仅在 rulesmake 场景中使用。

### 5.2 方案

创建统一 Action（位于 hall 插件），替代所有散落的 `findSuitableRoomId`。

```typescript
@ct.action({name:"Action_FindSuitableRoom"})
export class Action_FindSuitableRoom extends ct.BTAction {
    open(tick: ct.Tick): void {
        // 1. 检查是否需要进入新手教程
        if (CMNewPlayerLessonHelp.isNewPlayer()) {
            let singlePlayerCfg = ct.additionConfig.getFunction("singleplayer")
            let roomId = singlePlayerCfg?.roomId
            if (roomId) {
                this.setOutputData({ roomId })
                this.status = ct.b3.SUCCESS
                return
            }
        }

        // 2. 既有逻辑：根据携带财富查找最适合的房间
        let roomId = this.findSuitableRoomId()
        this.setOutputData({ roomId })
        this.status = ct.b3.SUCCESS
    }

    // 合并 BaseLayer / SecondLayer / Action_GetSuitableRoomId 中的查找逻辑
    private findSuitableRoomId(): number { /* ... */ }
}
```

### 5.3 改造点

| 文件 | 改动 |
|------|------|
| `BaseLayer.ts:868` | 替换为 `runAction("Action_FindSuitableRoom")` |
| `SecondLayer.ts:318` | 替换为 `runAction("Action_FindSuitableRoom")` |
| `RMRoomList.ts:302` | 替换为 `runAction("Action_FindSuitableRoom")` |
| `AreaNode.ts:177-182` | KEY_SYSGAME 分支替换为 CMNewPlayerLesson 检查 |
| `RoomNode.ts:132-137` | KEY_SYSGAME 分支替换为 CMNewPlayerLesson 检查 |

---

## 6. 游戏场景集成

### 6.1 GameInfo: 数据访问与 CP 请求

GameInfo 新增教程相关方法：

```typescript
// GameInfo.ts

static checkNeedLesson(): boolean {
    return CMNewPlayerLessonHelp.isNewPlayer()
}

static isLessonPlaying(): boolean {
    return window["_isLessonPlaying"] === true
}

// 请求 CP 发奖并标记完成（客户端驱动）
static requestClaimTutorialReward(callback: (success: boolean, rewardGold: number) => void) {
    ct.CommonCPInterFace.client_request('convert', (res: any) => {
        if (res && res.data && res.id === 1) {
            let plugin = ct.centerCtrl.getPlugin('CMNewPlayerLessonPlugin')
            if (plugin) {
                plugin.updateState({ isCompleted: true, rewardGold: res.data.rewardGold })
            }
            callback(res.data.success, res.data.rewardGold)
        } else {
            callback(false, 0)
        }
    }, { req: 'claimTutorialReward' })
}
```

### 6.2 Game.ts onLoad 教程启动

```typescript
onLoad(): void {
    // ... 既有初始化逻辑 ...
    if (GameInfo.checkNeedLesson()) {
        this.startLesson()
    }
}

private startLesson() {
    this._isLessonPlaying = true
    window["_isLessonPlaying"] = true
    this._lesson = new TqGameLesson(GameInfo)
    // 注入发奖回调
    this._lesson.onLessonReward = () => this.claimTutorialReward()
    this._lesson.lessonStart().catch((err) => {
        console.error("TqGameLesson error:", err)
        // 兜底：直接请求发奖
        GameInfo.requestClaimTutorialReward(() => this.lessonCleanup())
    })
}
```

### 6.3 守卫点：集中式

不再在 8 个 Manager 中散布守卫，全部集中在 Game.ts：

- **`onLoad()`** — 启动教程状态机
- **`claimTutorialReward()`** — 教程 GETREWARD 时调用，请求 CP 发奖
- **`lessonCleanup()`** — 清理标记 + roomSkip
- **`OperateBtnsManager`** / **`PlayerInfoNode`** — 读取 `window["_isLessonPlaying"]` 做约束

```typescript
private claimTutorialReward() {
    GameInfo.requestClaimTutorialReward((success, rewardGold) => {
        this.lessonCleanup()
    })
}

private lessonCleanup() {
    this._isLessonPlaying = false
    window["_isLessonPlaying"] = false
    this.lessonRoomSkip()
}
```

---

## 7. TqGameLesson 模拟对局核心

### 7.1 模块结构

`game/scripts/common/TqGameLesson.ts`

```typescript
export class TqGameLesson {
    private gameInfo: GameInfo
    private sequence: LessonMessage[]  // LessonData 全部阶段
    private isEnding: boolean = false

    constructor(gameInfo: GameInfo) {
        this.gameInfo = gameInfo
        this.sequence = LessonData.getSequence()
    }

    // 启动状态机
    async lessonStart(): Promise<void> { /* ... */ }

    // 推进到下一步
    nextStep(): void { /* ... */ }

    // 结算跳转
    roomSkip(): void { /* ... */ }

    // 标记结束
    lessonOver(): void { this.isEnding = true }

    isEnding(): boolean { return this.isEnding }

    // 约束按钮可见性
    hideBtns(): void { /* ... */ }

    // 时间段延迟
    private delay(seconds: number): Promise<void> {
        return new Promise(resolve => setTimeout(resolve, seconds * 1000))
    }
}
```

### 7.2 LessonData

`game/scripts/common/LessonData.ts`

单文件，与 Lua 版 LessonData.lua 1:1 对应（14 阶段）。

```typescript
export interface LessonMessage {
    type: MessageType      // RSP | NOTIFY | CUSTOM
    msgID: number
    handler: string
    data?: any
    delay: number          // 分发前等待秒数
}

export class LessonData {
    static getSequence(): LessonMessage[] {
        return [
            // Stage 1: EnterGame
            { type: MessageType.RSP, msgID: 0x1001, handler: 'dealRsp', data: {...}, delay: 1.0 },
            // Stage 2: 发牌
            // ... 14 个阶段共 3500+ 行
        ]
    }
}
```

### 7.3 状态机时序

```typescript
async lessonStart(): Promise<void> {
    try {
        for (const msg of this.sequence) {
            await this.delay(msg.delay)

            switch (msg.type) {
                case MessageType.RSP:
                    // 模拟服务端响应 → 调用 GameInfo 对应方法
                    this.dealRsp(msg.msgID, msg.data)
                    break

                case MessageType.NOTIFY:
                    // 模拟服务端推送 → 调用 GameInfo 对应方法
                    this.dealNotify(msg.msgID, msg.data)
                    break

                case MessageType.CUSTOM:
                    // 客户端控制消息 → 自处理
                    this.dealCustom(msg.msgID)
                    break
            }
        }
    } catch (err) {
        // xpcall 等价兜底
        console.error("lessonStart error:", err)
        GameInfo.requestClaimTutorialReward(() => { /* 兜底清理 */ })
    }
}
```

### 7.4 CUSTOM 控制消息

| ID | 名称 | 处理 |
|----|------|------|
| 1 | BETTERCARD | 出牌提示「选更好的牌」，更新 UI 引导预制体 |
| 2 | GETREWARD | 触发 `onLessonReward` 回调 → `claimTutorialReward` |
| 3 | LESSONOVER | `lessonOver()` → `setIsEnding(true)` |
| 4 | FIRSTHU | 首次胡牌特殊处理 |
| 5 | CANHUTINGINFO | 显示"可以胡牌"提示 |
| 6 | NOTCALQYS | 不计缺一色规则标记 |

### 7.5 结算与奖励

对局中金币变化流程：

```
LessonData 模拟对局
  ↓ 局内每次胡牌：客户端本地算法算出假金币变化，仅 UI 展示
  ↓ 对局结束 → CUSTOM GETREWARD 触发
  → TqGameLesson.onLessonReward 回调
  → Game.ts claimTutorialReward()
    → GameInfo.requestClaimTutorialReward()
      → client_request('convert', cb, { req: 'claimTutorialReward' })
      → convert OnClientRequest 处理
        → 发金币（失败不影响标记）
        → 设 bit 5
        → 返回 { success, rewardGold }
    → 更新 DataCenter
    → lessonCleanup()
    → roomSkip()
```

---

## 8. UI 教学引导系统

### 8.1 预制体方案

- **大厅手指引导**：`plugins/hall/.../prefabGuide` — 已有，复用
- **游戏内教学总预制体**：包含多个子预制体（遮罩、高亮区域、手指动画）
- 位置：`common_skin/common/prefab/`（由用户管理）

### 8.2 LessonData 驱动

TqGameLesson 在执行过程中根据当前阶段操作总预制体：

```typescript
// 在 CUSTOM 控制消息或特定 RSP 处理后
private updateGuideUI(step: string) {
    switch (step) {
        case 'showIntroduceLesson':
            // 展示流程介绍
            break
        case 'showExchangeCardLesson':
            // 高亮换牌区域
            break
        case 'showFixMissLesson':
            // 高亮定缺区域
            break
        // ... 9 种引导
    }
}
```

按钮约束：通过 `Game.ts` 设置教程标记位，`OperateBtnsManager` 读取该标记位决定按钮可见性（最少入侵）。

---

## 9. 数据流

### 9.1 新玩家进入流程

```
玩家打开大厅
  → FirstLayer.updateGuide() 显示手指动画（已有逻辑，nBout==0）
  → 玩家点击房间/快速开始
    → RoomNode/AreaNode.onClick()
    → Action_FindSuitableRoom
      → CMNewPlayerLessonHelp.isNewPlayer() == true
      → additionConfig.singleplayer.roomId 返回
    → ct.startGame(singleplayerRoomId)
    → Game.scene 加载 → Game.onLoad()
      → GameInfo.checkNeedLesson() == true
      → TqGameLesson.lessonStart()
```

### 9.2 老玩家进入流程

```
玩家打开大厅
  → FirstLayer.updateGuide() 不显示（nBout>0）
  → 玩家点击房间
    → Action_FindSuitableRoom
      → CMNewPlayerLessonHelp.isNewPlayer() == false
      → 正常房间查找逻辑
    → ct.startGame(realRoomId)
```

### 9.3 教程完成流程

```
TqGameLesson 14 阶段模拟对局结束
  → CUSTOM GETREWARD 触发
  → TqGameLesson.onLessonReward 回调
  → Game.ts claimTutorialReward()
    → GameInfo.requestClaimTutorialReward()
      → client_request('convert', cb, { req: 'claimTutorialReward' })
      → convert OnClientRequest
        → 发金币（先发奖，失败继续）
        → 设 bit 5
        → 返回 { success, rewardGold }
    → 更新 DataCenter（isCompleted = true）
    → lessonCleanup()
    → roomSkip()
      → Action_FindSuitableRoom（此时 isNewPlayer == false）
      → ct.startGame(realRoomId)
```

### 9.4 中断重入流程

```
玩家在教程中途杀进程
  → 重新打开 App → 进入大厅
  → OnLogon 执行 → nBout == 0，bit 未设
  → migrationResult 推送 isCompleted == false
  → 玩家点击房间
  → isNewPlayer() == true
  → 重新进入教程对局
  → 第 1 阶段重新开始

教程完成后杀进程
  → CP 已存 bit 5
  → OnLogon 推送 isCompleted == true
  → 不再进入教程
```

---

## 10. 实现顺序

| 步骤 | 内容 | 依赖 | 验证标准 |
|------|------|------|---------|
| 1 | CP convert 扩展（bit flag + OnClientRequest + OnLogon） | 无 | 接口返回正确状态 |
| 2 | 创建 CMNewPlayerLesson 插件结构（Def/Help/Plugin） | 无 | 插件注册成功，DataCenter 初始化 |
| 3 | HallPlugin handleMigrationResult 扩展 | Step 2 | 收到推送后更新 DataCenter |
| 4 | 实现 GameInfo.checkNeedLesson / requestClaimTutorialReward | Step 2-3 | CP 请求调用成功 |
| 5 | 创建 Action_FindSuitableRoom 统一房间查找 | Step 4 | 新玩家跳转到 singleplayer 房间 |
| 6 | 改造入口（RoomNode + AreaNode 替换 KEY_SYSGAME） | Step 5 | 新玩家进入教程房间 |
| 7 | 迁移 TqGameLesson + LessonData 核心模块 | 无 | 状态机可启动 |
| 8 | Game.ts onLoad 集成 + 教程启动 | Step 7 | onLoad 触发 lessonStart |
| 9 | 结算集成 + claimTutorialReward 调用链 | Step 4 + 8 | 教程结束完成发奖+跳转 |
| 10 | PlayerInfoNode 头像点击拦截 + OperateBtnsManager 约束 | Step 7 | 教程期间操作受控 |
| 11 | UI 引导预制体集成 | Step 7 | 教程期间正确显示引导 |
