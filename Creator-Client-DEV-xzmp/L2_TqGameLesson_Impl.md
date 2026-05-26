# L2 新手教程系统 — 实际实现笔记

> 本笔记记录 Creator 客户端新手教程系统的**实际实现**（与 Impl 文档的计划方案不同）。
> 实现过程涉及：教程状态管理、BTree Action 路由、Lesson 模块、Game 流程接入、runAction 统一调用模式。

---

## 一、架构概览（实际实现 vs 计划方案）

| 方面 | Impl 计划方案 | 实际实现 |
|------|-------------|---------|
| 教程状态插件 | 新建 `CMNewPlayerLessonPlugin`（独立插件） | HallPlugin 的 `onDataReducer` + `HallDefine` 常量 |
| 状态读取 | `CMNewPlayerLessonHelp` static 方法 | `HallHelp.getTutorialState()` static 方法 |
| 房间路由 Action | 新建 `Action_FindSuitableRoom` | 复用/改造 hall 插件的 `Action_GetSuitableRoomId`（基于 rulesmake 版） |
| 数据源 | CP 独立推送到新插件 | CP 的 `migrationResult` 经 HallPlugin.handleMigrationResult 统一推送 |
| 教程控制器 | `TqGameLesson` 类 + Promise 链 | `TqLessonCtrl` 单例 + `setTimeout` 调度 |
| 状态默认值 | `isCompleted: false` | `isCompleted: true`（无状态即视为已对局，防误触） |
| 房间跳转 | 在 Game.ts 中通过 `lessonRoomSkip()` 内联 | `GameInfo.roomSkip()` 调用 `Action_GetSuitableRoomId` |

---

## 二、数据流

```
CP convert_xzmp push (migrationResult)
  → HallPlugin.handleMigrationResult(data.newPlayerLesson)
    → this.dispatch({ type: "Hall_UpdateTutorialState", value: { isCompleted, rewardGold } })
      → HallPlugin.onDataReducer 存入 Redux 状态
        → ct.dataCenter.getState("HallPlugin").get("Hall_TutorialState")
          → HallHelp.getTutorialState()          ← HallHelp 静态 getter
          → GameInfo.getTutorialState()           ← GameInfo 跨插件读取
            → TqLessonCtrl.isNeedLesson()          ← 判断是否启动教程
```

### 状态结构

```typescript
// HallDefine.ts
export interface TutorialState {
    isCompleted: boolean  // 是否已完成（默认 true 防止误触发）
    rewardGold: number    // 奖励金币数
}

export const TutorialDataType = { State: "Hall_TutorialState" }
export const TutorialReduceType = { UpdateState: "Hall_UpdateTutorialState" }
```

### HallPlugin.onDataReducer

```typescript
onDataReducer(state, action) {
    // 初始化默认值
    if (!state) {
        return { [TutorialDataType.State]: { isCompleted: true, rewardGold: 0 } }
    }
    // 处理更新
    case TutorialReduceType.UpdateState:
        return { [TutorialDataType.State]: action.value }
}
```

**设计要点**：默认 `isCompleted: true` 是关键决策。因为大多数玩家不是新玩家，如果默认 `false` 会导致所有无状态用户（如未登录、测试环境）错误触发教程。只有 CP 明确推送了 `isCompleted: false` 时教程才会启动。

---

## 三、Action_GetSuitableRoomId — 房间路由统一

### 3.1 背景

项目中最初有 5+ 处散布的 `findSuitableRoomId` 实现：

| 位置 | 原始方式 |
|------|---------|
| `BaseLayer.ts` | private 方法 + `HallHelp.findSuitableRoomId()` 调用 |
| `SecondLayer.ts` | private 方法 + `HallHelp.findSuitableRoomId()` 调用 |
| `RMRoomList.ts` | private 方法 |
| `rulesmake/actions/action_getsuitableroomid.ts` | BTree Action（无教程路由） |
| `RoomNodeEx.ts` | inline 教程检查 |

### 3.2 统一方案

创建一个 Hall 插件的 BTree Action，包含教程路由 + 房间查找。规则：
1. 教程未完成 → 返回 roomId 13162
2. 教程已完成 → 正常找房（findRoom2 → findRoom → roomList[0] 容错）

```typescript
// plugins/hall/scripts/actions/action_getsuitableroomid.ts
@ct.action({ name: "Action_GetSuitableRoomId" })
export class Action_GetSuitableRoomId extends ct.BTAction {
    open(tick: ct.Tick): void {
        // 1. 新手教程未完成 → 直接进教程房
        if (!this.isTutorialCompleted()) {
            this.setOutputData({ roomId: 13162, roomName: "新手教程" });
            this.status = ct.b3.SUCCESS;
            return;
        }
        // 2. 正常找房
        let roomId = this.findSuitableRoomId();
        // ...
    }
    // isTutorialCompleted(): 从 HallPlugin dataCenter 读
    // findSuitableRoomId(): 合并 BaseLayer + rulesmake 逻辑
    // findRoom2 + findRoom + getBalancedRoomByRoom
}
```

### 3.3 调用方式

所有调用方统一使用 `ct.btreeCenter.runAction`：

```typescript
ct.btreeCenter.runAction("Action_GetSuitableRoomId", (bSuccess, data) => {
    if (bSuccess && data) {
        let roomId = data.roomId;
        // 使用 roomId 做后续处理
    }
});
```

### 3.4 转换的调用方

| 文件 | 方法 | 转换内容 |
|------|------|---------|
| `BaseLayer.ts` | `onQuickStartClick` | do-while + HallHelp.findSuitableRoomId → runAction |
| `BaseLayer.ts` | `updateQuickStartInfo` | do-while + HallHelp.findSuitableRoomId → runAction |
| `SecondLayer.ts` | `updateRoomList` | 先创建房间节点，再 runAction 高亮推荐 |
| `SecondLayer.ts` | `updateRoomSelected` | HallHelp.findSuitableRoomId → runAction |
| `RMRoomList.ts` | `updateRecommondRoom` | this.findSuitableRoomId → runAction |

### 3.5 调用注意点

**async 回调重构**：`runAction` 是异步回调模式，原来的同步代码需要重构：

- **onQuickStartClick**：`ct.startGame` 移入 runAction 回调内部
- **updateQuickStartInfo**：按钮文本更新移入回调
- **updateRoomList**：房间节点先创建（不带推荐高亮），runAction 回调再设置 `setSelected`
- **updateRoomSelected**：整个方法体移入回调

关键：Behavior Tree Action 在当前帧同步执行 `open()` 方法（无异步操作），所以回调几乎是立即触发的。但代码风格上仍需按回调书写。

---

## 四、TqLessonCtrl — 教程控制器

### 4.1 单例模式

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

### 4.2 isNeedLesson() 守门条件

三个条件缺一不可：
1. `GameInfo.getTutorialState().isCompleted === false` — CP 确认未完成
2. `_roomInfo` 不为空 — 已注入房间信息
3. `isHZXLRoom(roomInfo.nRoomID) === true` — 房间 ID 为 13162

### 4.3 LessonData 调度

14 个阶段，每阶段若干条消息。RSP/NOTIFY/CUSTOM 三种类型，通过 `setTimeout` 控制延迟：

```typescript
private dispatchCurrentMessage() {
    let stage = getLessonStage(this._curStageIndex);
    let msg = stage.messages[this._curMsgIndex];
    let timeoutId = setTimeout(() => {
        this.processMessage(msg);
    }, msg.delay * 1000);
    this._timeoutIds.push(timeoutId);
}
```

### 4.4 消息类型处理

| 类型 | 处理方式 |
|------|---------|
| RSP (1) | 通过 `eventCenter.emit(GameEvent.onLessonRsp, data)` 分发给监听方 |
| NOTIFY (2) | 通过 `eventCenter.emit(GameEvent.onLessonNotify, data)` 分发给监听方 |
| CUSTOM (3) | 本地处理：BETTERCARD/GETREWARD/LESSONOVER/FIRSTHU/CANHUTINGINFO/NOTCALQYS |

### 4.5 生命周期

```
lessonStart()
  → _running = true, _isEnding = false
  → emit onLessonStart
  → dispatchCurrentMessage() (依次派发各阶段消息)

nextStep()
  → _curMsgIndex++，若阶段结束则 _curStageIndex++
  → 所有阶段完成 → lessonOver()

lessonOver()
  → _running = false, setIsEnding(true)
  → claimReward() → GameInfo.claimTutorialReward() (CP 发奖)
    → 成功后 → roomSkip() → GameInfo.roomSkip() (runAction 跳真实房间)
```

---

## 五、Game.ts/Hooks 接入点

### 5.1 教程启动

在 `GamePlugin.event_onGameEnterOK` 中，`onEnterGameOK` emit 后：

```typescript
let lessonCtl = TqLessonCtrl.getInstance();
let tableInfo = (GameInfo as any).tableInfo;
if (tableInfo) {
    lessonCtl.setCurRoomInfo({ nRoomID: tableInfo.ei?.nRoomID || tableInfo.nRoomID });
}
if (lessonCtl.isNeedLesson()) {
    lessonCtl.lessonStart();
}
```

### 5.2 结算拦截

在 `ResultManager.showResult` 中：

```typescript
let lessonCtl = TqLessonCtrl.getInstance();
if (lessonCtl && lessonCtl.isEnding()) {
    lessonCtl.roomSkip();  // 跳过结算 UI 直接跳转
    return;
}
```

---

## 六、GameInfo — 教程接口

新增的 tutorial 方法位于 GameInfo 末尾（6241-6307 行）：

| 方法 | 用途 |
|------|------|
| `getTutorialState()` | 从 HallPlugin 的 dataCenter 读取状态 |
| `isTutorialCompleted()` | 快捷判断 |
| `queryTutorialState()` | 通过 CP client_request 查询 |
| `claimTutorialReward()` | 通过 CP client_request 领奖 + 更新本地状态 |
| `roomSkip()` | 调用 Action_GetSuitableRoomId 跳转真实房间 |

```typescript
// roomSkip 实现
public roomSkip() {
    ct.btreeCenter.runAction("Action_GetSuitableRoomId", (bSuccess, data) => {
        if (bSuccess && data && data.roomId) {
            ct.startGame(data.roomId, ct.StartGameSource.kSourceQuickStart);
        } else {
            ct.startGame(0, ct.StartGameSource.kSourceQuickStart);
        }
    });
}
```

---

## 七、文件变更清单

### 修改的文件

| 文件 | 变更 |
|------|------|
| `plugins/hall/scripts/Define.ts` | 新增 `TutorialState` 接口、`TutorialDataType`、`TutorialReduceType` |
| `plugins/hall/scripts/HallPlugin.ts` | `handleMigrationResult` 新增 `newPlayerLesson` 分支；`onDataReducer` 初始化+更新状态 |
| `plugins/hall/scripts/layers/HallHelp.ts` | 新增 `getTutorialState()` / `isTutorialCompleted()` / `getTutorialRewardGold()` |
| `plugins/hall/scripts/layers/BaseLayer.ts` | onQuickStartClick + updateQuickStartInfo 改用 runAction；移除 findSuitableRoomId 相关 private 方法 |
| `plugins/hall/scripts/layers/SecondLayer.ts` | updateRoomList + updateRoomSelected 改用 runAction；移除 findSuitableRoomId 相关 private 方法 |
| `plugins/rulesmake/scripts/views/RMRoomList.ts` | updateRecommondRoom 改用 runAction；移除 findSuitableRoomId 相关 private 方法 |
| `game/scripts/GameInfo.ts` | 新增 getTutorialState / isTutorialCompleted / queryTutorialState / claimTutorialReward / roomSkip |
| `game/scripts/GamePlugin.ts` | event_onGameEnterOK 中注入教程启动 |
| `game/scripts/manager/ResultManager.ts` | showResult 中拦截 isEnding |
| `game/scripts/event/game-event.ts` | 新增 onLessonStart / onLessonRsp / onLessonNotify 等事件常量 |
| `game/scripts/components/Game.ts` | 引入 TqLessonCtrl（已删除 inline 教程代码，交由 GamePlugin 控制） |

### 新建的文件

| 文件 | 说明 |
|------|------|
| `plugins/hall/scripts/actions/action_getsuitableroomid.ts` | BTree Action：教程路由 + 房间查找统一 |
| `game/scripts/lesson/TqLessonDef.ts` | 教程常量、枚举、消息类型 |
| `game/scripts/lesson/TqLessonData.ts` | 14 阶段教程数据（简化 TS 版，含牌局细节） |
| `game/scripts/lesson/TqLessonCtrl.ts` | 教程控制器单例 |

---

## 八、关键设计决策

### 8.1 为什么用 HallPlugin 而不用独立插件？

1. state 已经在 HallPlugin 内由 `handleMigrationResult` 统一管理，新增独立插件反而增加跨插件通信
2. `migrationResult` 推送机制在 HallPlugin 中已经是现成架构
3. HallHelp 作为 static getter 集中地已经承担了类似角色（装饰品、周月卡、等级等）

### 8.2 为什么用 HallHelp static getter + GameInfo 跨插件读？

- HallHelp 使用 `this.dataCenter.getState("HallPlugin")` 直接读取其他插件的状态
- GameInfo 使用同样模式，`this.dataCenter.getState("HallPlugin")`
- 不需要通过事件/消息传递，数据流更短

### 8.3 为什么默认值设 `isCompleted: true`？

这是个安全设计。如果玩家没有 CP 推送的教程状态（如新账号还未完成 migration），默认 `true` 意味着"已对局"，不会错误触发教程。只有 CP 明确说"这个玩家需要教程"，教程才会激活。

### 8.4 为什么用 `runAction` 而不是静态方法？

- Action 可以在未来被行为树编辑器配置、替换、扩展
- 统一入口点便于后期添加逻辑（如 A/B 测试、灰度控制）
- 消除多份重复的 `findSuitableRoomId` 实现

---

## 九、已知要点

1. **rulesmake 也有同名 Action**：`rulesmake/scripts/actions/action_getsuitableroomid.ts` 定义了同样的 Action 名。Hall 插件加载后会覆盖它。如 rulesmake 侧有特殊需求可能需要处理冲突。

2. **RoomNodeEx.ts 保留 inline 教程检查**：点击具体房间节点时，教程检查直接使用 `HallHelp.isTutorialCompleted()`，不走 runAction。因为这是"点击特定房间"的流程，不是"找合适的房间"。

3. **lessonstatus 协议未使用**：本实现没有依赖 GameSvr 的 `lessonstatus` 协议（450680），而是完全基于 CP convert 模块的状态管理。如有需要可以后续接入。

4. **教程中途杀进程**：玩家在教程对局中途杀掉进程重进时，`lessonstatus` 仍是 1（服务器未接到领奖请求），CP 的 `isCompleted` 仍是 false，教程会重新触发。教程内的金币变化是 LessonData 中硬编码的假数据，不会实际到账。
