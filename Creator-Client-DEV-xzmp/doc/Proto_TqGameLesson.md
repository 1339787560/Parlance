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
| CMNewPlayerLesson | CP 插件，管理教程完成状态和奖励 |
| TqGameLesson | 客户端纯逻辑模块，模拟对局状态机 |
| LessonData | 14 阶段 3500+ 行预定义消息序列 |
| singleplayer | additionConfig 中配置的单机房间 |
| roomSkip | 教程结束后跳转到真实房间 |

---

## 2. 架构总览

```
+-- HallPlugin ------------------------------+
|   CMNewPlayerLesson DataCenter 托管         |
|   handleMigrationResult() → nBout != 0     |
|   时自动标记完成                            |
+--------------------------------------------+
          |
          | this.dataCenter.getState()
          v
+-- GameInfo --------------------------------+
|   取 CMNewPlayerLesson 数据项               |
|   请求 markLessonComplete → CP 发奖         |
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
|   ntfGameWin() → 触发结算 → markComplete   |
+--------------------------------------------+
```

### 2.1 组件职责

| 组件 | 类型 | 位置 | 职责 |
|------|------|------|------|
| CMNewPlayerLessonPlugin | CP 插件 | `plugins/cmnewplayerlesson/` | CP 数据托管、请求处理 |
| CMNewPlayerLessonHelp | Help 类 | `plugins/cmnewplayerlesson/` | 静态数据访问方法 |
| TqGameLesson | 纯模块 | `game/scripts/common/TqGameLesson.ts` | 模拟对局状态机 |
| LessonData | 数据文件 | `game/scripts/common/LessonData.ts` | 14 阶段预定义消息 |
| Action_FindRoom | BT Action | `plugins/hall/scripts/actions/` | 统一房间查找 |
| GameInfo | 数据管理 | `game/scripts/GameInfo.ts` | CP 数据访问 + 请求 |
| Game | 主控制器 | `game/scripts/components/Game.ts` | 启动守卫 |

---

## 3. CP 插件: CMNewPlayerLesson

### 3.1 目录结构

```
plugins/cmnewplayerlesson/
├── scripts/
│   ├── CMNewPlayerLessonDef.ts      # 常量、数据类型、接口定义
│   ├── CMNewPlayerLessonHelp.ts     # 静态 Helper (extend ct.BaseFunctionNode)
│   └── CMNewPlayerLessonPlugin.ts   # 插件类 (extend ct.BasePlugin)
```

### 3.2 数据定义 (CMNewPlayerLessonDef)

```typescript
export namespace CMNewPlayerLessonDef {
    export const PluginName = 'CMNewPlayerLessonPlugin'
    export const MODULE_NAME = 'cmnewplayerlesson'

    // 客户端 → CP 请求
    export const REQ_QUERY_STATE = 'queryLessonState'
    export const REQ_MARK_COMPLETE = 'markLessonComplete'

    export const DataType = {
        LessonState: "CMNewPlayerLesson_LessonState",
    }

    export const ReduceType = {
        UpdateLessonState: "CMNewPlayerLesson_UpdateLessonState",
    }

    // CP 返回的玩家状态
    export interface LessonState {
        isCompleted: boolean      // 是否已完成教程
        rewardGold?: number       // 奖励金币数（仅 markComplete 返回时携带）
    }
}
```

### 3.3 插件类 (CMNewPlayerLessonPlugin)

```typescript
@ct.plugin
export class CMNewPlayerLessonPlugin extends ct.BasePlugin {
    onInit() {
        // 初始化状态
        return new Promise<void>((resolve, reject) => {
            // onInit 时不强求请求 CP（保持启动速度）
            // 由 HallPlugin 在适当时机调用查询
            resolve()
        })
    }

    onDataReducer(state, action) {
        // 标准 reducer 模式
    }

    // 查询教程状态
    queryState(callback: (state: LessonState) => void) {
        ct.CommonCPInterFace.client_request(
            MODULE_NAME,
            (res: any) => {
                if (res?.id === 1 && res?.data) {
                    this.dispatch({
                        type: ReduceType.UpdateLessonState,
                        value: { isCompleted: res.data.isCompleted || false }
                    })
                    callback({ isCompleted: res.data.isCompleted || false })
                } else {
                    callback({ isCompleted: false })
                }
            },
            { req: REQ_QUERY_STATE }
        )
    }

    // 标记教程完成（由 GameInfo 调用）
    markComplete(callback: (result: { success: boolean, rewardGold: number }) => void) {
        ct.CommonCPInterFace.client_request(
            MODULE_NAME,
            (res: any) => {
                if (res?.id === 1 && res?.data) {
                    this.dispatch({
                        type: ReduceType.UpdateLessonState,
                        value: { isCompleted: true, rewardGold: res.data.rewardGold }
                    })
                    callback({ success: true, rewardGold: res.data.rewardGold || 0 })
                } else {
                    callback({ success: false, rewardGold: 0 })
                }
            },
            { req: REQ_MARK_COMPLETE }
        )
    }
}
```

### 3.4 数据访问 (CMNewPlayerLessonHelp)

```typescript
@ccclass('CMNewPlayerLessonHelp')
export class CMNewPlayerLessonHelp extends ct.BaseFunctionNode {
    // 是否已完成教程
    static isCompleted(): boolean {
        let state = this.dataCenter.getState(CMNewPlayerLessonDef.PluginName)
        return state?.get(CMNewPlayerLessonDef.DataType.LessonState)?.isCompleted || false
    }

    // 是否为新玩家（需完成教程）
    static isNewPlayer(): boolean {
        if (this.isCompleted()) return false
        let nBout = ct.LocalCache.getInt("userbout", 0)
        return nBout <= 0
    }
}
```

### 3.5 CP 接口协议

| 请求 | req 值 | 发送方 | 返回值 |
|------|--------|--------|--------|
| 查询状态 | `queryLessonState` | HallPlugin | `{ isCompleted: boolean }` |
| 标记完成 | `markLessonComplete` | GameInfo | `{ success: boolean, rewardGold: number }` |

CP 端数据存储：

```typescript
// CP 端维护
interface PlayerTutorialState {
    userId: number
    isCompleted: boolean          // 教程完成标记
    rewardGold: number            // 奖励金币数
}
```

- `isCompleted` 不由客户端直接设置
- 仅在 `markLessonComplete` 成功发奖后由 CP 置位
- CP 端通过 `modsvr.parse_gameresult` 获取玩家局数（nBout）

---

## 4. 大厅集成 (HallPlugin)

### 4.1 数据托管

HallPlugin 在 `onInit()` 中获取 CMNewPlayerLesson 数据：

```typescript
onInit() {
    // 启动时查询教程状态
    let lessonPlugin = ct.centerCtrl.getPlugin('CMNewPlayerLessonPlugin')
    if (lessonPlugin) {
        lessonPlugin.queryState((state) => {
            // 状态已写入 DataCenter
        })
    }
}
```

### 4.2 迁移处理

HallPlugin.handleMigrationResult() 中发现玩家 nBout != 0 时，
自动将玩家标记为"已完成教程"（防止已玩过的玩家被错误拦截）：

```typescript
handleMigrationResult(data) {
    // ... 现有迁移逻辑 ...

    // 迁移：如果已有对局记录，标记教程完成
    if (data.nBout != null && data.nBout > 0) {
        ct.CommonCPInterFace.client_request('cmnewplayerlesson', (res) => {
            if (res?.id === 1) {
                console.log("cmnewplayerlesson migration markComplete ok")
            }
        }, { req: 'markLessonComplete' })
    }
}
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

// 检查玩家是否需要教程
static checkNeedLesson(): boolean {
    return CMNewPlayerLessonHelp.isNewPlayer()
}

// 请求标记教程完成并领取奖励
static requestMarkLessonComplete(callback: (success: boolean, rewardGold: number) => void) {
    let plugin = ct.centerCtrl.getPlugin('CMNewPlayerLessonPlugin') as CMNewPlayerLessonPlugin
    if (!plugin) {
        callback(false, 0)
        return
    }
    plugin.markComplete((result) => {
        if (result.success) {
            // 更新本地金币显示
            // depositModel.addGold(result.rewardGold)
        }
        callback(result.success, result.rewardGold)
    })
}
```

### 6.2 Game.ts onLoad 教程启动

```typescript
// Game.ts onLoad()
onLoad(): void {
    // ... 既有初始化逻辑 ...

    // 检查是否需要启动教程
    if (GameInfo.checkNeedLesson()) {
        this.startLesson()
    }
}

private startLesson() {
    // 教程进行中标记
    this._isLessonPlaying = true

    // 创建教程状态机实例
    this._lesson = new TqGameLesson(GameInfo.getInstance())

    // 启动异步状态机
    this._lesson.lessonStart().catch((err) => {
        console.error("TqGameLesson error:", err)
        // xpcall 等价兜底：直接请求标记完成
        GameInfo.requestMarkLessonComplete()
    })
}
```

### 6.3 守卫点：集中式

不再在 8 个 Manager 中散布守卫，全部集中在 Game.ts：

- **`onLoad()`** — 启动教程状态机
- **`ntfGameWin()`** — 教程结算时调 `markLessonComplete`
- **`OperateBtnsManager`** — 教程期间按钮可见性由 TqGameLesson 控制（不入侵 Manager）

```typescript
// Game.ts: 拦截 ntfGameWin
// 原流程: GameConnect → GameInfo.ntfGameWin
// 教程中: TqGameLesson → direct call → GameInfo.ntfGameWin → Game.ts 检测

// Game.ts 中监听 ntfGameWin 完成
onGameWinComplete() {
    if (this._isLessonPlaying) {
        // 教程对局结束 → 请求发奖
        GameInfo.requestMarkLessonComplete((success, rewardGold) => {
            if (success) {
                this._lesson.setIsEnding(true)
                this.roomSkip()  // 跳转到真实房间
            } else {
                // 发奖失败，仍然结束教程
                this._lesson.lessonOver()
                this.roomSkip()
            }
        })
    }
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
        GameInfo.requestMarkLessonComplete()
    }
}
```

### 7.4 CUSTOM 控制消息

| ID | 名称 | 处理 |
|----|------|------|
| 1 | BETTERCARD | 出牌提示「选更好的牌」，更新 UI 引导预制体 |
| 2 | GETREWARD | 调 `reqLessonReward()` → CP `markLessonComplete` |
| 3 | LESSONOVER | `lessonOver()` → `setIsEnding(true)` |
| 4 | FIRSTHU | 首次胡牌特殊处理 |
| 5 | CANHUTINGINFO | 显示"可以胡牌"提示 |
| 6 | NOTCALQYS | 不计缺一色规则标记 |

### 7.5 结算与奖励

对局中金币变化流程：

```
LessonData 模拟对局
  ↓ 局内每次胡牌：客户端本地算法算出假金币变化，仅 UI 展示
  ↓ 对局结束（LESSONOVER 前最后一个阶段）
  → GameInfo.ntfGameWin(fakeWinData)  // 假结算数据
  → Game.ts onGameWinComplete()
    → GameInfo.requestMarkLessonComplete()
      → CP markLessonComplete 接口
        → CP 发奖成功 → isCompleted = true
        → CP 返回 rewardGold
      → 更新本地 DataCenter
      → lessonOver()
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
  → ntfGameWin（假结算数据）
  → GameInfo.requestMarkLessonComplete()
    → CP markLessonComplete
      → CP 发奖 + 置位 isCompleted
    → 返回 { success: true, rewardGold }
  → 更新 DataCenter
  → lessonOver()
  → roomSkip()
    → Action_FindSuitableRoom（此时 isNewPlayer == false）
    → ct.startGame(realRoomId)
```

### 9.4 中断重入流程

```
玩家在教程中途杀进程
  → 重新打开 App → 进入大厅
  → HallPlugin.onInit() → queryLessonState
    → CP 返回 { isCompleted: false }
  → 玩家点击房间
  → isNewPlayer() == true
  → 重新进入教程对局
  → 第 1 阶段重新开始

教程完成后杀进程
  → CP 已存 isCompleted = true
  → 不再进入教程
```

---

## 10. 实现顺序

| 步骤 | 内容 | 依赖 | 验证标准 |
|------|------|------|---------|
| 1 | 创建 CMNewPlayerLesson 插件结构（Def/Help/Plugin） | 无 | 插件注册成功，DataCenter 初始化 |
| 2 | 实现 CP 接口 queryState + markLessonComplete | CP 端配合 | HallPlugin 能查询状态 |
| 3 | 实现 GameInfo.checkNeedLesson / requestMarkLessonComplete | 步骤 2 | 接口调用成功 |
| 4 | 创建 Action_FindSuitableRoom 统一房间查找 | 步骤 3 | 新玩家跳转到 singleplayer 房间 |
| 5 | 改造现有 findSuitableRoomId 调用点 | 步骤 4 | 所有位置使用同一 Action |
| 6 | 迁移 TqGameLesson + LessonData 核心模块 | 无 | 状态机可启动 |
| 7 | Game.ts onLoad 集成 + 教程启动 | 步骤 6 | onLoad 触发 lessonStart |
| 8 | 结算集成 + markComplete 调用链 | 步骤 3 + 7 | 教程结束完成发奖 |
| 9 | HallPlugin 迁移处理（nBout != 0 → markComplete） | 步骤 2 | 已玩过玩家不被拦截 |
| 10 | UI 引导预制体集成 | 步骤 6 | 教程期间正确显示引导 |
| 11 | 按钮约束集成 | 步骤 6 | 教程期间只显示可操作按钮 |
