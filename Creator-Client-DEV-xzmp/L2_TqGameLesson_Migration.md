# L2 新手教程迁移指南 — Lua → Creator

> 将旧版 Lua 客户端 TqGameLesson（客户端模拟对局）迁移到 Creator 客户端所需关注的全部要点。

## 一、架构概览

旧版方案是 **客户端模拟对局**：TqGameLesson 插件用预定义 protobuf 消息直接注入到 BaseGameController，不走网络。Creator 端需要决定：**是沿用同样架构，还是改为服务端驱动的真实对局？**

如果沿用模拟对局，以下所有要点都需要在 Creator 中重建；如果改为服务端驱动，则只需要迁移触发逻辑和结果处理，不需要模拟消息。

---

## 二、服务端协议（不受迁移影响）

以下协议由客户端 → 服务端，Creator 端只需照发：

| 消息 ID | 方向 | 用途 |
|---------|------|------|
| 450680 (GR_LESSON_DATA_REQ) | C→S | 请求新手教程信息 |
| — | S→C | 返回 `{lessonstatus = 1}`（或 0） |

服务器返回 `lessonstatus == 1` 是整个教程的**必要条件**。参数由第三方接口 `isXXXSupported("playerlesson")` 控制，客户端无法自行开启。

协议上的 callback 监听点（在 Lua 中由 `onNotifyReceived` 处理）也需要迁移。

---

## 三、触发链（必须完整迁移）

```
大厅入口 → 新手引导动画 → 点击"单机房" → RoomManager 发送 EnterGameType.kOfflineGame
  → 游戏场景加载 → BaseGameLoadingCtrl 请求 GR_LESSON_DATA_REQ
    → 收到 lessonstatus=1 → isNeedLesson() = true → lessonStart()
```

### 分段迁移要点

### 3.1 大厅新手引导 — FirstLayer

[FirstLayer.lua:56](D:\Codlib\douque\xzmx\ClientLua\src\trunk\src\app\GameHall\room\views\FirstLayer.lua#L56) 中的新手引导：

```lua
function GamePublicInterface:needShowGuide(rooms)
    local cache = CacheModel:getCacheByKey("guidetime")
    if cache.guidetime then return false end
    local user = mymodel('UserModel'):getInstance()
    if user.nBout ~= nil and user.nBout > 0 then return false end
    return true
end
```

**条件**：`guidetime` 缓存为空 + 玩家对局数 `nBout == 0`。

**效果**：在"单机房"按钮位置播放手指动画（`guide_finger.csb`），引导新玩家点击。

**迁移要求**：Creator 中需等价实现：
- 检查 `nBout == 0` 的新玩家
- 在大厅"单机房"入口显示高亮引导动画
- 动画资源从 `guide_finger.csb` 转换成 Creator 动画系统

### 3.2 单机房入口 — RoomManager

[RoomManager.lua:158-165](D:\Codlib\douque\xzmx\ClientLua\src\trunk\src\app\GameHall\room\ctrl\RoomManager.lua#L158) 中 `offlineRoom` 分支发送 `EnterGameType.kOfflineGame`。

RoomConfig.lua 中 `offlineRoom.enable = false`，但新手教程实际**不走 offlineRoom**（走 RoomID 13162）。所以入口按钮虽然叫"单机房"，但行为不是传统单机，而是新手教程。

**迁移要求**：Creator 中"单机房"按钮存在即可，不需要实现真正的离线单机逻辑，但需要确保新手玩家能看到这个入口（不受 enable=false 影响）。

### 3.3 房间信息注入 — RoomManager

[RoomManager.lua:274-275](D:\Codlib\douque\xzmx\ClientLua\src\trunk\src\app\GameHall\room\ctrl\RoomManager.lua#L274)：

```lua
local TqGameLesson = require("src.app.plugins.tqPlayerLesson.TqGameLesson"):getInstance()
TqGameLesson:setCurRoomInfo(PUBLIC_INTERFACE.GetCurrentRoomInfo())
```

进入任何房间时都需要将当前房间信息注入 TqGameLesson，供 `isNeedLesson()` 中的 `isHZXLRoom(roomID)` 检查使用。

**迁移要求**：进入房间时，必须调用 `TqGameLesson.setCurRoomInfo(roomInfo)`，否则 isNeedLesson 永为 false。

### 3.4 加载场景启动 — BaseGameLoadingCtrl

[BaseGameLoadingCtrl.lua:141-144](D:\Codlib\douque\xzmx\ClientLua\src\trunk\src\app\game\base\loading\BaseGameLoadingCtrl.lua#L141)：

```lua
if TqGameLesson:isNeedLesson() then
    TqGameLesson:lessonStart()  -- 启动教程对局
end
```

**关键**：加载场景是教程的真正起点。`lessonStart()` 启动协程开始逐条派发 LessonData 消息。

**迁移要求**：Creator 的游戏加载流程中，必须检查 `isNeedLesson()`，在加载完成后调用 `lessonStart()`。

---

## 四、isNeedLesson 守门 — 25+ 守卫点

`isNeedLesson()` 在 Lua 客户端有 25+ 处调用，分布在以下 9 个组件中：

### 4.1 BaseGameController（核心控制器）

| 行号 | 作用 |
|------|------|
| 297 | 初始化的早期流程分支 |
| 769 | 游戏对局阶段，拦截常规逻辑 |
| 1261 | `setIsEnding(false)` 重置 |
| 2849 | 调用 `showIntroduceLesson()` |
| 2100 | 重置结束状态 |
| 3589 | 某个条件分支 |
| 5683-5684 | 调用 `nextStep()` 推进教程 |
| 7782 | 条件分支 |
| 9257 | 调用 `showExchangeCardLesson()` |
| 9656 | 调用 `showFixMissLesson()` |
| 9742 | 调用 `showHZLesson()` |
| 10569 | `not isNeedLesson()` 作为牌型显示的条件 |
| 12259-12260 | 调用 `nextStep()` |

**迁移要求**：Creator 的主游戏控制器需要同样的守卫模式：在关键流程（发牌、换牌、出牌、胡牌、结算等）中判断 `isNeedLesson()`，为 true 时跳过常规网络流程，等待教程的消息注入。

### 4.2 BaseGameRequest（网络层）

| 行号 | 作用 |
|------|------|
| 672 | 拦截某个网络请求 |
| 1416-1417 | 拦截 + `nextStep()` |
| 1459-1460 | 拦截 + `nextStep()` |
| 1562-1563 | 拦截 + `nextStep()` |
| 1799-1800 | 拦截 + `nextStep()` |
| 1850-1851 | 拦截 + `nextStep()` |
| 2075 | 拦截 |

**迁移要求**：Creator 的网络模块需要：当 `isNeedLesson()` 为 true 时，**跳过真实的网络请求发送**（因为教程不走网络），部分位置还需要主动调用 `nextStep()` 推进教程流程。

### 4.3 其他组件

| 文件 | 行号 | 作用 |
|------|------|------|
| BaseGameScene | 439, 1888 | 场景 UI 行为分支 |
| BaseGameData | 523 | 数据初始化分支 |
| BaseGameInfo | 783 | 游戏信息分支 |
| BaseGamePlayerModel | 101 | 玩家模型分支 |
| BaseGamePlayerCtrl | 294 | 玩家控制分支 |
| MJOpeBtnCtrl | 336, 377 | 胡牌/过牌按钮位置提示 |
| CardRecorderIcon | 59 | 记牌器图标隐藏 |
| MyGameCardTypeIntro | 57 | 牌型介绍隐藏 |
| MyGameResultCtrl | 229, 232, 294, 296 | 结算界面处理 + roomSkip |
| MyGameResultView | 991-1028 | 结算视图的 isEnding 检查 |
| BaseGameStartBtnsCtrl | 203-219 | 对局开始按钮的 isEnding 检查 |

**迁移要求**：以上每个点都需要在 Creator 找到等价位置，添加 `isNeedLesson()` 守卫。

### 4.4 isNeedLesson 函数本身

```lua
function TqGameLesson:isNeedLesson()
    if not cc.exports.isPlayerLessonSupport() then  -- 第三方接口开关
        return false
    end
    local roomID = currentRoomInfo.nRoomID
    if not my.isHZXLRoom(roomID) then               -- RoomID != 13162
        return false
    end
    if self._data and self._data.lessonstatus == 1 then  -- 服务器确认
        return true
    end
    return false
end
```

**三个条件缺一不可**：
1. `isPlayerLessonSupport()` — 第三方配置开关（Lua 中映射为 `isXXXSupported("playerlesson")`）
2. `isHZXLRoom(roomID)` — 检查房间 ID 是否是 13162（红中血流系列房间）
3. `_data.lessonstatus == 1` — 服务器协议确认

**迁移要求**：Creator 需要调用同样的服务端接口来判断是否支持教程，并正确传递 RoomID。

---

## 五、LessonData 模拟消息 — 最重的部分

LessonData.lua（3500+ 行）是教学对局的全部数据。共 14 个阶段，每个阶段包含若干条消息。

### 消息类型

| 类型 | 值 | 路由函数 | 用途 |
|------|-----|----------|------|
| RSP | 1 | dealRsp(msgID, data) | 模拟网络响应 |
| NOTIFY | 2 | dealNotify(msgID, data) | 模拟网络推送 |
| CUSTOM | 3 | dealCustom(msgID) | 客户端控制流 |

### 分发方式

```lua
lessonStart() → for each stage → for each msg → CoFunc.wait(0.x s) → dispatch
```

使用 Cocos2DX `Scheduler` + coroutine（`CoFunc`）控制时序。

### 迁移选项

| 选项 | 工作量 | 优缺点 |
|------|--------|--------|
| A. 直接移值 LessonData | 大 | 保持完全一致的行为，但数据量大 |
| B. 简化模拟逻辑 | 中 | 减少预定义消息量，用代码按规则生成 |
| C. 改为服务端驱动对局 | 最大 | 不需要模拟消息，需服务端配合改造 |

### 必须迁移的消息

无论选哪个选项，以下关键数据流必须重现：

1. **EnterGame RSP** — 进入游戏响应（含玩家信息、座位号、房间配置）
2. **卡牌数据** — `nChairCards`（发牌）、补花、换牌结果
3. **游戏流程** — AI 摸牌出牌序列、玩家摸牌出牌序列
4. **结算数据** — `nOldDeposits`、`nTotalDepositDiff`
5. **CUSTOM 控制消息** — BETTERCARD / GETREWARD / LESSONOVER / FIRSTHU / CANHUTINGINFO / NOTCALQYS

### 时序控制

Lua 用 `CoFunc.wait(seconds)` 在消息间插入延迟。Creator 需要等价机制（如 `setTimeout` / `Promise.delay` / `cc.tween`）。

---

## 六、CUSTOM 客户端控制消息

| ID | 名称 | 作用 | 迁移要求 |
|----|------|------|---------|
| 1 | BETTERCARD | 出牌时提示玩家选更好的牌 | Creator 同时需要对应的 UI 引导 |
| 2 | GETREWARD | 领取教程奖励，调 `reqLessonReward()` | 协议不变，透传即可 |
| 3 | LESSONOVER | 标记教程结束，调 `lessonOver()` | 结束状态管理 |
| 4 | FIRSTHU | 首次胡牌特殊处理 | 逻辑等价 |
| 5 | CANHUTINGINFO | 显示"可以胡牌"提示 | UI 提示迁移 |
| 6 | NOTCALQYS | 本局不计缺一色 | 游戏规则设定 |

---

## 七、结算与跳转 (roomSkip / lessonOver)

### 结果界面 (MyGameResultCtrl/MyGameResultView)

Lua 中的处理：
1. `MyGameResultCtrl` 检查 `TqGameLesson:isEnding()`
2. 如果 true，不显示正常结算界面，而是调用 `TqGameLesson:roomSkip()`

```lua
-- MyGameResultCtrl.lua:229-232
if TqGameLesson:isEnding() then
    TqGameLesson:roomSkip()
    return
end
```

### roomSkip 逻辑

```lua
-- TqGameLesson.lua:522-541
function TqGameLesson:roomSkip()
    -- 根据玩家当前金币选择可进入的最高等级房间
    -- 通过 GamePublicInterface:getQuickStartRoomID() 计算
    -- 如果金币不足 → 提示"金币不足"
    -- 如果金币足够 → 直接跳转到真实房间
end
```

### lessonOver 逻辑

```lua
-- TqGameLesson.lua:544-548
function TqGameLesson:lessonOver()
    self:setIsEnding(true)
    self:getReward()  -- 发 GR_LESSON_DATA_REQ 领取奖励
end
```

**迁移要求**：Creator 的结算流程必须：
- 检查 `isEnding()`
- 如果是教程对局，跳过常规结算 UI
- 调用 `roomSkip()` 将玩家引导到真实房间
- 处理金币不足的情况

### 对局开始按钮 (BaseGameStartBtnsCtrl)

```lua
-- BaseGameStartBtnsCtrl.lua:203-204
if TqGameLesson:isEnding() then
    TqGameLesson:roomSkip()
```

**注意**：有两个地方有同样的逻辑（line 203 和 line 218），因为"再来一局"和"返回大厅"按钮都要跳过。

---

## 八、UI 教学引导 — 高亮/遮罩/手指动画

TqGameLesson 包含一套完整的 UI 引导系统（未在 L2 中深入展开，但迁移时必碰）：

| 函数 | 用途 |
|------|------|
| `showIntroduceLesson()` | 流程介绍 |
| `showExchangeCardLesson(wPos)` | 指示换牌操作区域 |
| `showFixMissLesson(wPos)` | 指示定缺操作区域 |
| `showHZLesson()` | 指示补花操作区域 |
| `showMissCardLesson()` | 指示打缺牌 |
| `showGuoCardLesson(wPos)` | 指示过牌按钮 |
| `showTingTipLesson()` | 听牌提示 |
| `showBetterCardLesson()` | 更好的出牌建议 |
| `showHuLesson(wPos)` | 指示胡牌按钮 |

底层能力：
- `digMask(contentSize, position)` — 在遮罩上挖洞，高亮目标区域
- `playFingerAni(pos)` — 手指点击动画
- `hideBtns()` / `hideAllPanel()` — 隐藏干扰按钮

**迁移要求**：Creator 需要实现等价的高亮/遮罩/手指动画系统。建议做成可复用的 UI 引导组件，而非与教程逻辑强耦合。

---

## 九、完整文件依赖清单

### Lua 侧涉及的所有文件（迁移范围）

| 类别 | 文件 | 迁移优先级 |
|------|------|-----------|
| **教程核心** | `plugins/tqPlayerLesson/TqGameLesson.lua` | 必须 |
| **教程数据** | `plugins/tqPlayerLesson/LessonData.lua` | 必须 |
| **游戏控制器** | `game/base/game/BaseGameController.lua` | 必须（25+ 守卫点） |
| **网络层** | `game/base/network/BaseGameRequest.lua` | 必须（7 守卫点） |
| **加载场景** | `game/base/loading/BaseGameLoadingCtrl.lua` | 必须（启动点） |
| **大厅引导** | `GameHall/room/views/FirstLayer.lua` | 建议（新手体验） |
| **房间管理器** | `GameHall/room/ctrl/RoomManager.lua` | 必须（setCurRoomInfo） |
| **结算界面** | `game/my/result/MyGameResultCtrl.lua` | 必须（roomSkip） |
| **结算视图** | `game/my/result/MyGameResultView.lua` | 必须（isEnding） |
| **开始按钮** | `game/base/start/BaseGameStartBtnsCtrl.lua` | 必须（roomSkip） |
| **操作按钮** | `game/mj/opebtn/MJOpeBtnCtrl.lua` | 建议（提示位置） |
| **牌型介绍** | `game/my/cardtypeintro/MyGameCardTypeIntro.lua` | 建议 |
| **记牌器** | `plugins/cardrecorder/CardRecorderIcon.lua` | 建议 |
| **玩家模型** | `game/base/player/BaseGamePlayerModel.lua` | 建议 |
| **玩家控制** | `game/base/player/BaseGamePlayerCtrl.lua` | 建议 |
| **场景** | `game/base/game/BaseGameScene.lua` | 建议 |
| **数据** | `game/base/BaseGameData.lua` | 建议 |
| **信息** | `game/base/BaseGameInfo.lua` | 建议 |
| **玩家公共接口** | `game/common/GamePublicInterface.lua` | 必须（needShowGuide） |
| **功能开关** | `BaseModule/AdditionalKey.lua` | 必须（isPlayerLessonSupport） |
| **大厅房间配置** | `HallConfig/RoomConfig.lua` | 参考 |
| **模块加载** | `game/common/CommonFunc.lua` | 参考（前缀链） |

### 协议依赖

| 协议 | 说明 |
|------|------|
| GR_LESSON_DATA_REQ (450680) | 请求/接收教程信息 |
| GR_LESSON_DATA_REQ CUSTOM → reward | 领取教程奖励 |

---

## 十、关键注意事项

### 10.1 RoomID 13162 特殊处理

教程使用 RoomID 13162，这是一个**线上不存在的虚拟房间 ID**。Creator 需要：
- 能够将此 ID 映射到 UI 上显示"新手场"
- 不走正常的房间匹配逻辑
- `isHZXLRoom()` 检查（系列函数）需要移植

### 10.2 `isEnding()` 标志位

```lua
function TqGameLesson:isEnding()
    return self._isEnding or false
end
```

被结算界面、开始按钮等多个地方使用。教程结束后设为 true，防止玩家进入正常结算 UI。

**必须迁移**，并在教程结束时设置。

### 10.3 `rebuildGameWinData()`

AI 用户名替换逻辑。教程中对局玩家的真实用户名是 wuchen0001~wuchen0004，需要在结算前替换成 `"玩家199708563"` 样式的伪装名。

```lua
function TqGameLesson:rebuildGameWinData(data)
    -- 遍历数据，将 szUsername 替换
end
```

**可选**：如果 Creator 的教程对局不再硬编码用户名，此函数可能不需要。

### 10.4 `hideBtns()` — 按钮隐藏

教程期间需要隐藏"设置""表情""托管"等按钮，防止玩家交互导致状态错乱。在 Creator 中同样需要：

```lua
function TqGameLesson:hideBtns()
    -- 隐藏各种操作按钮
end
```

### 10.5 第三方配置 `isXXXSupported("playerlesson")`

这是旧版 Lua 对接的第三方 SDK 接口。Creator 需要映射到等价的能力检查接口。如果该接口返回 false，整个教程功能关闭。

### 10.6 批量 require 方式

Lua 使用 `Filelist.lua` 的 `LuaFileList` 机制实现按需加载。Creator 的模块系统（import/require）不同，所有 `require("src.app.plugins.tqPlayerLesson.TqGameLesson")` 需要沿 Creator 的模块路径重新映射。

---

## 十一、迁移建议顺序

| 步骤 | 内容 | 验证标准 |
|------|------|---------|
| 1 | 移植 TqGameLesson 核心类 + isNeedLesson | isNeedLesson 正确返回 |
| 2 | 移植协议收发（GR_LESSON_DATA_REQ） | 收到 lessonstatus=1 |
| 3 | 移植触发链（大厅→加载→lessonStart） | lessonStart 被调用 |
| 4 | 移植 LessonData + 消息分发（RSP/NOTIFY/CUSTOM） | 教程对局开始 |
| 5 | 添加游戏控制器守卫点（BaseGameController） | 教程流程不被中断 |
| 6 | 添加网络层守卫点（BaseGameRequest） | 不走真实网络 |
| 7 | 移植 UI 引导系统（遮罩/高亮/手指） | 引导正确显示 |
| 8 | 移植结算/roomSkip | 教程结束后正确跳转 |
| 9 | 移植大厅新手引导（FirstLayer） | 新玩家看到手指动画 |
| 10 | 其他守卫点补全 | 无遗漏 |
