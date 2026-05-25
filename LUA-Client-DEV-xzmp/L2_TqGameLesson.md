# L2 新手教程 (TqGameLesson) — 客户端模拟对局

> 来源：`plugins/tqPlayerLesson/TqGameLesson.lua` + `LessonData.lua`

## 核心机制

**不是本地对局（离线单机），而是客户端模拟对局**。`TqGameLesson` 插件在客户端进程内用预定义 protobuf 消息模拟一整局麻将，不走真实网络。其他三个"玩家"是纯数据构造的 AI，没有独立的逻辑、没有托管、没有 avatar 数据。

## 触发链

```
大厅点"单机房"
  → RoomManager 发送 EnterGameType.kOfflineGame
    → 客户端向服务器发 GR_LESSON_DATA_REQ (msgID 450680)
      → 服务器返回 {lessonstatus = 1}
        → isNeedLesson() = true
          → TqGameLesson:lessonStart() 启动
```

### isNeedLesson() 守门逻辑

```lua
-- TqGameLesson.lua:220-237
function TqGameLesson:isNeedLesson()
    if not cc.exports.isPlayerLessonSupport() then   -- 功能开关
        return false
    end
    local roomID = currentRoomInfo.nRoomID
    if not my.isHZXLRoom(roomID) then                 -- roomID != 13162
        return false
    end
    if self._data and self._data.lessonstatus == 1 then  -- 服务器确认
        return true
    end
    return false
end
```

三个条件缺一不可：功能支持 + 房间 ID 13162 + 服务器返回 lessonstatus=1。

`BaseGameController` 中 25+ 处调用 `isNeedLesson()`，控制 UI 按钮显隐、网络消息拦截等行为。

## Room ID 13162

特殊房间 ID，专用于新手教程：
- 客户端硬编码在 LessonData 中
- 线上不存在此 ID 的真实场次（最低为初级场）
- 大厅显示的"新手场"是 UI 层基于此 ID 渲染的假名称

## 数据流架构

### MSG_TYPE 三类消息

| 类型 | 值 | 来源 | 作用 |
|------|-----|------|------|
| RSP | 1 | LessonData | 模拟服务端响应（进入游戏、换牌、出牌、胡牌等应答） |
| NOTIFY | 2 | LessonData | 模拟服务端推送（玩家进入、游戏开始、摸牌、出牌、结算等通知） |
| CUSTOM | 3 | LessonData | 客户端控制流（显示换牌提示、领奖励、教程结束等） |

### CUSTOM_MSG_ID

| ID | 常量名 | 作用 |
|----|--------|------|
| 1 | BETTERCARD | 提示玩家选更好的牌型 |
| 2 | GETREWARD | 领取教程奖励 |
| 3 | LESSONOVER | 教程结束，跳转房间 |
| 4 | FIRSTHU | 首次胡牌特殊处理 |
| 5 | CANHUTINGINFO | 可胡牌提示 |
| 6 | NOTCALQYS | 不计算缺一色的通知 |

### LESSON_STATUS 状态机

| 值 | 常量名 | 含义 |
|----|--------|------|
| 0 | NONE | 未开始 |
| 1 | INTRODUCE | 教程介绍 |
| 2 | EXCHANGECARD | 换牌阶段 |
| 3 | FIXMISS | 定缺阶段 |
| 4 | HZ | 补花阶段 |
| 5 | MISSCARD | 打缺阶段 |
| 6 | GUOCARD | 过牌/摸牌阶段 |
| 7 | TINGTIP | 听牌提示 |
| 8 | BETTERCARD | 更好的出牌建议 |
| 9 | HUCARD | 胡牌 |

## 14 阶段对局流程 (LessonData)

| 阶段 | 内容 | 消息数 |
|------|------|--------|
| 1 | EnterGame RSP → 设置房间/椅子信息 | 13 |
| 2 | 玩家换牌、定缺、同意开始 | 35 |
| 3 | 发牌，show better card 提示 | 9 |
| 4 | AI 补花 | 9 |
| 5 | AI 出牌，玩家补花 | 13 |
| 6 | 玩家定缺选花色 | 28 |
| 7 | 玩家出牌（含 better card 提示） | 9 |
| 8 | AI 出牌，玩家摸牌出牌 | 15 |
| 9 | 自摸，胡牌，听牌提示 | 28 |
| 10 | AI 出牌，玩家摸牌 | 10 |
| 11 | AI 出牌，玩家吃碰杠 | 17 |
| 12 | 听牌 → AI 出牌 → 点炮 → 胡牌 | 15 |
| 13 | 结算 → 领奖励 | 20 |
| 14 | LESSONOVER → 跳转到真实房间 | 7 |

## 时序控制

使用 Cocos2DX 的 `Scheduler` + coroutine（`CoFunc`）精确控制消息派发时序：

```
lessonStart()
  → for each stage in LessonData
    → for each message in stage
      → dispatch RSP/NOTIFY/CUSTOM
      → CoFunc.wait(0.x s)   -- 模拟网络延迟
```

非真实网络，所以**不存在倒计时归零托管**——所有时间间隔都是预设的。

## 伪造玩家数据

### 原始数据（LessonData）

| 椅子 | UserID | 用户名 | 初始金币 | 对局数 |
|------|--------|--------|---------|-------|
| 0 (玩家) | 733811 | wuchen0002 | 100000 | — |
| 1 (AI) | 733813 | wuchen0004 | 0 | 99 |
| 2 (AI) | 733812 | wuchen0003 | 0 | 105 |
| 3 (AI) | 733810 | wuchen0001 | 0 | 89 |

### 结算时替换

`rebuildGameWinData()` 将 AI 的原始用户名替换为如 `"玩家199708563"` 的伪装名，使其看起来像真实在线玩家。

### 金币快照

| 阶段 | 玩家 | AI-1 | AI-2 | AI-3 |
|------|------|------|------|------|
| 结算前 | 90000 | 70000 | 20000 | 70000 |
| 结算后 | 250000 | 0 | 0 | 0 |
| 最终盈亏 | +160000 | -70000 | -20000 | -70000 |

**你的观察完全吻合**：2×70000, 1×20000。

## 教程结束后跳转 (roomSkip)

`roomSkip()` 根据玩家当前金币量计算应跳转到哪个真实房间：

- **金币足够** → 跳到初级场
- **金币不够** → 提示金币不足

## 新手引导动画

`FirstLayer.lua:56` 中，`GamePublicInterface:needShowGuide()` 检查 `user.nBout == 0`（对局数为 0 的新玩家），显示大厅新手引导动画（红圈高亮单机房入口）。

## 相关文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 教程核心 | `ClientLua/src/trunk/src/app/plugins/tqPlayerLesson/TqGameLesson.lua` | isNeedLesson + lessonStart + 三路分发 |
| 教程数据 | `ClientLua/src/trunk/src/app/plugins/tqPlayerLesson/LessonData.lua` | 3500+ 行 14 阶段硬编码消息 |
| 房间配置 | `ClientLua/src/trunk/src/app/HallConfig/RoomConfig.lua` | offlineRoom enable=false, 单机房入口 |
| 房间管理器 | `ClientLua/src/trunk/src/app/GameHall/room/ctrl/RoomManager.lua` | kOfflineGame 发送 + setCurRoomInfo |
| 大厅引导层 | `ClientLua/src/trunk/src/app/GameHall/room/views/FirstLayer.lua` | 新手引导动画 (nBout==0) |
| 公共接口 | `ClientLua/src/trunk/src/app/game/common/GamePublicInterface.lua` | needShowGuide + getQuickStartRoomID |
| 游戏控制器基类 | `ClientLua/src/trunk/src/app/game/base/game/BaseGameController.lua` | 25+ isNeedLesson 守卫点 |
| 模块加载 | `ClientLua/src/trunk/src/app/game/common/CommonFunc.lua` | 前缀链 Offline→My→MJ→Base |

## 关键注意事项

- **单机房 (offlineRoom) 配置已关闭** (`enable = false`)——新手不走单机房，走 RoomID 13162
- **isNeedLesson 不可绕过**——25+ 个守卫点分布在 BaseGameController 各处，绕过任意一处都会导致 UI 错乱
- **修改 LessonData 可改变教程体验**——增减阶段/消息需同步调整 LESSON_STATUS 状态机
- **coroutine 时序依赖**——修改 wait 延迟可能破坏对局节奏感
