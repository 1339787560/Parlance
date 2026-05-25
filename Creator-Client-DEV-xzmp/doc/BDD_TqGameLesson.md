# BDD: 新手教程对局 (TqGameLesson)

> 基于 Proto_TqGameLesson.md 衍生的行为驱动开发场景描述。
> 每一个场景 = 一条可验证的行为规则。

---

## 场景 1: CP 插件的状态查询

**背景：** CMNewPlayerLessonPlugin 已注册，HallPlugin 已初始化。

**规则 1.1：首次进入的玩家状态为未完成**

```
Given 玩家从未登录过游戏
When  HallPlugin.onInit() 查询教程状态
Then  调用 CMNewPlayerLessonPlugin.queryState()
And   CP 返回 { isCompleted: false }
And   DataCenter 中 LessonState.isCompleted == false
```

**规则 1.2：已完成教程的玩家状态为已完成**

```
Given 玩家已完成过新手教程（CP 端 isCompleted = true）
When  HallPlugin.onInit() 查询教程状态
Then  CP 返回 { isCompleted: true }
And   DataCenter 中 LessonState.isCompleted == true
```

**规则 1.3：CP 服务异常时默认为未完成**

```
Given CP 服务不可用
When  queryState() 发起请求
Then  回调返回 { isCompleted: false }
And   DataCenter 保持默认值
And   不影响玩家进入游戏（不因 CP 异常卡住）
```

---

## 场景 2: CMNewPlayerLessonHelp 数据访问

**规则 2.1：新玩家判定**

```
Given 玩家局数 nBout == 0
And   LessonState.isCompleted == false
When  CMNewPlayerLessonHelp.isNewPlayer()
Then  返回 true
```

**规则 2.2：已玩过但未标记的玩家视为新玩家**

```
Given 玩家局数 nBout > 0（数据迁移尚未执行）
And   LessonState.isCompleted == false
When  CMNewPlayerLessonHelp.isNewPlayer()
Then  返回 false（因为 nBout > 0）
```

**规则 2.3：已完成教程的玩家不是新玩家**

```
Given LessonState.isCompleted == true
When  CMNewPlayerLessonHelp.isNewPlayer()
Then  返回 false（无论 nBout 值）
```

---

## 场景 3: 房间查找 Action

**背景：** Action_FindSuitableRoom 已注册。

**规则 3.1：新玩家点击房间 → 跳转到 singleplayer 房间**

```
Given 当前玩家是新玩家（isNewPlayer() == true）
And   additionConfig.singleplayer 中配置了 roomId
When  Action_FindSuitableRoom 执行
Then  返回 singleplayer 配置的 roomId
```

**规则 3.2：缺少 singleplayer 配置时走正常逻辑**

```
Given 当前玩家是新玩家
And   additionConfig.singleplayer 未配置或 roomId 为空
When  Action_FindSuitableRoom 执行
Then  进入既有 findSuitableRoomId 逻辑
```

**规则 3.3：老玩家点击房间 → 正常房间查找**

```
Given 当前玩家不是新玩家（isNewPlayer() == false）
When  Action_FindSuitableRoom 执行
Then  直接进入既有 findSuitableRoomId 逻辑
And   返回适合玩家财富等级的房间
```

---

## 场景 4: 入口拦截（RoomNode / AreaNode）

**规则 4.1：RoomNode 点击时走 Action_FindSuitableRoom**

```
Given 玩家在大厅房间列表
When  玩家点击一个房间节点（RoomNode.onClick()）
Then  处理流程变为：
      1. 检查 HallPlugin.gameClickRoomCB（已有）
      2. 调用 Action_FindSuitableRoom 获取目标房间
      3. ct.startGame(目标房间ID, ...)
```

**规则 4.2：AreaNode 点击时走 Action_FindSuitableRoom**

```
Given 玩家在大厅区域列表
When  玩家点击一个区域节点（AreaNode.onClick()）
Then  快速开始流程变为：
      1. 调用 Action_FindSuitableRoom 获取目标房间
      2. ct.startGame(目标房间ID, ...)
```

**规则 4.3：KEY_SYSGAME 分支替换**

```
Given 代码中现有 KEY_SYSGAME 拦截分支（nBout==0 时跳转）
When  代码重构后
Then  KEY_SYSGAME 分支被 CMNewPlayerLessonHelp.isNewPlayer() 检查替代
And   原有逻辑保留（additionConfig 配置仍可用）
```

---

## 场景 5: 教程对局启动

**背景：** 玩家已进入 singleplayer 房间的 game.scene。

**规则 5.1：新玩家进入游戏 → 自动启动教程**

```
Given 当前游戏场景 Game.scene 已加载
And  GameInfo.checkNeedLesson() == true
When  Game.onLoad() 执行
Then  调用 this.startLesson()
And  创建 TqGameLesson 实例
And  启动异步状态机 lessonStart()
And  Game._isLessonPlaying 标记为 true
```

**规则 5.2：老玩家进入游戏 → 不启动教程**

```
Given GameInfo.checkNeedLesson() == false
When  Game.onLoad() 执行
Then  lessonStart() 不被调用
And   游戏进入正常对局流程
```

---

## 场景 6: 教程状态机执行

**规则 6.1：LessonData 按序派发**

```
Given TqGameLesson 实例已创建
And  lessonStart() 已调用
When  状态机开始执行
Then  LessonData 中的消息按数组顺序逐一处理
And  每条消息派发前等待其 delay 指定的秒数
And  所有消息处理完后状态机正常结束
```

**规则 6.2：RSP 消息注入 GameInfo**

```
Given 当前处理的消息类型为 RSP
When  dealRsp(msgID, data) 被调用
Then  根据 msgID 调用 GameInfo 的对应方法（如设置手牌、结算数据等）
And   不经过网络层 GameConnect
```

**规则 6.3：NOTIFY 消息注入 GameInfo**

```
Given 当前处理的消息类型为 NOTIFY
When  dealNotify(msgID, data) 被调用
Then  根据 msgID 调用 GameInfo 的对应方法
And   不经过网络层 GameConnect
```

**规则 6.4：CUSTOM 消息客户端自处理**

```
Given 当前处理的消息类型为 CUSTOM
When  dealCustom(msgID) 被调用
Then  根据 msgID 执行对应的客户端控制逻辑：
      - GETREWARD → 触发 CP markLessonComplete
      - LESSONOVER → 标记教程结束
      - BETTERCARD/CANHUTINGINFO → 更新 UI 引导
      - FIRSTHU → 首次胡牌特殊处理
      - NOTCALQYS → 规则标记
```

**规则 6.5：状态机异常时兜底**

```
Given 状态机执行中抛出异常
When  lessonStart() 的 catch 块捕获到错误
Then  调用 GameInfo.requestMarkLessonComplete() 作为兜底
And   玩家不会卡在教程中
```

---

## 场景 7: 玩家操作约束

**规则 7.1：教程期间只显示可操作按钮**

```
Given 教程正在进行中（Game._isLessonPlaying == true）
When  OperateBtnsManager 更新按钮可见性
Then  只显示 TqGameLesson 当前阶段允许的操作按钮
And   "设置""表情""托管"等按钮隐藏
```

**规则 7.2：教程期间头像点击不弹出个人信息**

```
Given 教程正在进行中（Game._isLessonPlaying == true）
When  玩家点击自己或任意玩家的头像
Then  不弹出个人信息面板
And   点击事件被静默吞掉（无任何 UI 反馈）
```

**规则 7.3：玩家操作后推进状态机**

```
Given 状态机已派发一条等待玩家操作的消息
When  玩家完成提示的操作
Then  调用 TqGameLesson.nextStep() 推进到下一消息
```

---

## 场景 8: 结算与奖励

**规则 8.1：教程对局结束 → 请求发奖**

```
Given TqGameLesson 模拟对局结束（ntfGameWin 已调用）
And  Game._isLessonPlaying == true
When  Game.onGameWinComplete() 被触发
Then  调用 GameInfo.requestMarkLessonComplete()
And  等待 CP 返回发奖结果
```

**规则 8.2：发奖成功 → 标记完成 + 跳转**

```
Given CP markLessonComplete 返回 { success: true, rewardGold: N }
When  收到发奖成功回调
Then  DataCenter 中 LessonState.isCompleted 更新为 true
And  TqGameLesson.setIsEnding(true) 设置
And  调用 roomSkip() 跳转到真实房间
And  玩家金币增加 rewardGold
```

**规则 8.3：发奖失败 → 仍然结束教程**

```
Given CP markLessonComplete 返回 { success: false }
When  收到发奖失败回调
Then  TqGameLesson.lessonOver() 仍然执行
And  roomSkip() 仍然执行（玩家不卡住）
```

**规则 8.4：局内金币变化为假数据**

```
Given 教程对局阶段中
When  金币变化显示在 UI 上
Then  这些变化仅由 LessonData 硬编码数据驱动
And  未经过 CP 或 GameSvr 确认
And  玩家杀掉进程重新进入不会保留这些金币
```

---

## 场景 9: 教程结束跳转 (roomSkip)

**规则 9.1：roomSkip → 进入真实房间**

```
Given TqGameLesson.roomSkip() 被调用
When  执行房间跳转
Then  调用 Action_FindSuitableRoom（此时 isNewPlayer == false）
And  返回适合玩家的真实房间 ID
And  ct.startGame(realRoomId, ...) 执行跳转
```

---

## 场景 10: 数据迁移

**规则 10.1：已玩过玩家自动标记完成**

```
Given HallPlugin.handleMigrationResult() 收到数据
And  data.nBout > 0
When  迁移处理执行
Then  调用 markLessonComplete 请求 CP 标记完成
And  后续该玩家不再进入教程
```

**规则 10.2：新玩家迁移不受影响**

```
Given HallPlugin.handleMigrationResult() 收到数据
And  data.nBout == null 或 data.nBout == 0
When  迁移处理执行
Then  不调用 markLessonComplete
And  玩家继续享受教程引导
```

---

## 场景 11: 中断重入

**规则 11.1：教程未完成 → 重新进入可重新教程**

```
Given 玩家在教程中杀掉进程
And  CP 中 isCompleted == false
When  玩家重新进入 App → 点击房间
Then  isNewPlayer() == true
And  玩家重新进入 singleplayer 房间
And  教程从第 1 阶段重新开始
```

**规则 11.2：教程已完成 → 不再进入教程**

```
Given 玩家已完成教程（CP 中 isCompleted == true）
When  玩家重新进入 App → 点击房间
Then  isNewPlayer() == false
And  玩家直接进入真实房间
```

**规则 11.3：客户端不缓存教程完成状态**

```
Given 玩家在教程对局中途
When  检查本地存储
Then  isCompleted 状态仅存在于 CP 服务端
And  客户端 DataCenter 仅是运行态缓存
And  清除本地缓存/重装 App 不会导致 isCompleted 丢失
```

---

## 场景 12: UI 引导

**规则 12.1：大厅手指引导仅对 nBout==0 显示**

```
Given 玩家局数 nBout == 0
When  FirstLayer.updateGuide() 执行
Then  在默认区域上方显示 prefabGuide 手指动画

Given 玩家局数 nBout > 0
When  FirstLayer.updateGuide() 执行
Then  不显示手指引导动画
```

**规则 12.2：游戏内引导预制体按阶段更新**

```
Given 教程状态机在当前阶段包含 UI 引导标记
When  该阶段消息被派发
Then  TqGameLesson 更新总引导预制体的显示内容
And  对应区域显示遮罩/高亮/手指动画
```
