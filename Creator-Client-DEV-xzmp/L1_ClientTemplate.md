# L1 客户端模板 — Creator 客户端

> 模板层路径：`D:\CocosCreator2.0\Template`
>
> 客户端业务插件继承模板基类，模板提供通用能力：插件生命周期、数据中心、支付、行为树等。

## 1. 模板启动流程

### 入口链

| 阶段 | 所在文件 | 函数 | 功能 |
|------|---------|------|------|
| 引擎启动 | `assets/game/Init.ts` | `App.init()` | CocosCreator 物理系统、全局配置初始化 |
| 大厅加载 | `assets/plugins/hall/scripts/HallPlugin.ts` | `onInit()` | 大厅插件启动，加载房间列表、匹配入口 |
| 插件注册 | `assets/plugins/*/scripts/*Plugin.ts` | `onInit()` | 各业务插件自行注册到模块管理器 |
| 模板就绪 | Template `ct.js` / `BasePlugin.ts` | `ct.startup()` | 模板框架初始化完成，开始分发事件 |

### 模板框架启动细节

| 步骤 | 文件 | 关键调用 |
|------|------|---------|
| 全局上下文初始化 | `Template/ct.js` | `ct.init(options)` |
| 模块管理器启动 | `Template/core/CenterCtrl.ts` | `ct.centerCtrl.init()` |
| 数据中心初始化 | `Template/core/DataCenter.ts` | `ct.dataCenter.init(initialState)` |
| 插件扫描 | `Template/core/PluginManager.ts` | `ct.pluginManager.scanAndMount(slots)` |
| 插槽挂载 | `Template/slots/*` | `slot.mountAll()` |
| 大厅登录完成事件 | `Template/event/GameEvent.ts` | `@ct.event(ct.GameEvent.HallLoginEnd)` |

## 2. 插件系统工作流程

### 生命周期

```
引擎启动
  │ ct.centerCtrl.init()
  ▼
插件扫描 → PluginManager 遍历各插件目录
  │ @ct.plugin 装饰器注册
  ▼
onInit() → 注册视图、监听 CP 推送、拉取配置
  │
  ▼
checkSupported() → 判断插件是否对当前用户可用
  │
  ▼
onMount(slot) → 挂载入口节点到插槽
  │
  ▼
[用户交互] → postAction → ViewCtrl.onRequest → dataCenter.dispatch → onDataReducer → View.onUpdateView
  │
  ▼
onDestroy() → 清理通知、释放资源
```

### 五层模式文件索引

| 层 | 职责 | 所在文件 | 基类 |
|------|------|---------|------|
| Plugin | 生命周期、数据状态 | `<Plugin>/scripts/<Name>Plugin.ts` | `ct.BasePlugin` |
| Def | 常量、数据类型定义 | `<Plugin>/scripts/<Name>Def.ts` | — |
| Help | 工具函数 | `<Plugin>/scripts/<Name>Help.ts` | `ct.BaseFunctionNode` |
| ViewCtrl | 动作处理、数据源 | `<Plugin>/scripts/<Name>ViewCtrl.ts` | `ct.BaseViewCtrl` |
| View | 界面渲染 | `<Plugin>/scripts/view/<Name>View.ts` | `ct.BaseView` |

### 常用 API

| 目的 | 调用 | 所在文件 |
|------|------|---------|
| 注册插件 | `@ct.plugin` (装饰器) | `Template/decorator/PluginDecorator.ts` |
| 注册视图 | `ct.centerCtrl.addPopupView(this, "ViewName", { prefabPath, backgroundType })` | `Template/core/CenterCtrl.ts` |
| 打开插件视图 | `ct.centerCtrl.informPluginViewByName("PluginName", { viewName: "ViewName" })` | `Template/core/CenterCtrl.ts` |
| 关闭视图 | `this.destroy(ct.ViewExitCode.OK)` (ViewCtrl) | `Template/core/BaseViewCtrl.ts` |
| 获取插槽 | `ct.centerCtrl.getPluginSlot(ct.HALL_SLOTS.LEFTACTIVITY)` | `Template/core/CenterCtrl.ts` |
| 插入到插槽 | `slot.insertPlugin("PluginName")` | `Template/core/PluginSlot.ts` |
| 跨插件通信 | `ct.centerCtrl.postAction("TargetPlugin", { type, value })` | `Template/core/CenterCtrl.ts` |
| 监听服务端推送 | `this.notifySocket.addHandler(msgId, callback)` | `Template/network/NotifySocket.ts` |
| 弹出提示 | `ct.centerCtrl.showToast(msg)` | `Template/core/CenterCtrl.ts` |
| 奖励弹窗 | `ct.centerCtrl.showRewardDialog([{ propId, propCount }], delay, callback)` | `Template/core/CenterCtrl.ts` |

## 3. 数据中心工作流程

### 架构

数据中心采用 Redux 模式的状态管理，单向数据流：

```
View (用户操作)
  │ postAction({ type: ActionType.XXX })
  ▼
ViewCtrl.onRequest()
  │ this.dataCenter.dispatch({ type: ReduceType.XXX, value })
  ▼
Plugin.onDataReducer(state, action)
  │ 返回新 state（DataType 对应键）
  ▼
dataCenter 触发变更通知
  │ dataSource 自动同步
  ▼
View.onUpdateView(dataSource) → UI 刷新
```

### 核心接口

| 功能 | 函数 | 所在文件 |
|------|------|---------|
| 获取全局状态 | `ct.dataCenter.getState()` | `Template/core/DataCenter.ts` |
| 获取插件状态 | `this.dataCenter.getState(PluginName)` | `Template/core/DataCenter.ts` |
| 获取数值 | `this.dataCenter.getState(PluginName).getNumber(DataType.XXX)` | `Template/core/DataCenter.ts` |
| 触发 dispatch | `this.dataCenter.dispatch({ type: ReduceType.XXX, value })` | `Template/core/DataCenter.ts` |
| 创建数据源(View) | `createDataSource(createParams): ct.ViewDataSource` | `Template/core/BaseViewCtrl.ts` |
| 绑定数据源 | `dataSource.add("key", value)` | `Template/core/ViewDataSource.ts` |
| 读取数据(View) | `dataSource.get("key").value` | `Template/core/ViewDataSource.ts` |
| 数据变更通知 | `dataSource.check("key")` | `Template/core/ViewDataSource.ts` |
| Reducer 注册 | `onDataReducer(state, action)` | `Template/core/BasePlugin.ts` |

### DataType / ReduceType / ActionType 约定

```
Def.DataType       → dataCenter 存储键          (getState/setState)
Def.ReduceType     → dispatch 分发类型           (reducer 分支)
Def.ActionType     → postAction 动作类型         (ViewCtrl 动作分发)
```

## 4. 支付接口

| 功能 | 调用 | 所在文件 |
|------|------|---------|
| 发起支付 | `ct.payUtils.payForProduct(exchangeId, {}, callback)` | `Template/pay/PayUtils.ts` |
| 查询商品 | `ct.payUtils.queryProduct(productId)` | `Template/pay/PayUtils.ts` |
| 支付回调 | `(code: number, msg: string) => {}` | `Template/pay/PayUtils.ts` |
| 支付处理插件 | `assets/plugins/abtpay/scripts/AbtpayPlugin.ts` | `abtpay` 插件 |
| 商城插件 | `assets/plugins/shop/scripts/ShopPlugin.ts` | `shop` 插件 |

## 5. 行为树接口

行为树用于 AI 玩家决策、动画状态切换等场景。

| 功能 | 调用 | 所在文件 |
|------|------|---------|
| 创建行为树 | `ct.behaviorTree.create(config)` | `Template/behavior/BehaviorTree.ts` |
| 运行行为树 | `ct.behaviorTree.run(treeId, blackboard)` | `Template/behavior/BehaviorTree.ts` |
| 停止行为树 | `ct.behaviorTree.stop(treeId)` | `Template/behavior/BehaviorTree.ts` |
| 黑板存取 | `blackboard.set(key, value)` / `blackboard.get(key)` | `Template/behavior/Blackboard.ts` |
| 条件节点 | `conditionNode(conditionFn, success, failure)` | `Template/behavior/CompositeNode.ts` |
| 顺序节点 | `sequenceNode(children)` | `Template/behavior/CompositeNode.ts` |
| 选择节点 | `selectorNode(children)` | `Template/behavior/CompositeNode.ts` |
| 并行节点 | `parallelNode(children, policy)` | `Template/behavior/CompositeNode.ts` |

## 常用全局 API

| 功能 | 调用 | 所在文件 |
|------|------|---------|
| 渠道信息 | `ct.CommonFunc.getChannelKey()` | `Template/common/CommonFunc.ts` |
| 玩家局数 | `ct.LocalCache.getInt("userbout", 0)` | `Template/cache/LocalCache.ts` |
| 玩法类型 | `(curArea?.extension as any)?.type` | `Template/common/GameDef.ts` |
| 房间等级 | `(curRoom?.extension as any)?.custom?.roomlevel` | `Template/common/GameDef.ts` |
| Protobuf 解析 | `ct.Protobuf.ToString(new ct.BinaryStream(data), "UTF8")` | `Template/network/Protobuf.ts` |
| 事件监听 | `this.notifySocket.addHandler(msgId, handler)` | `Template/network/NotifySocket.ts` |
| 事件装饰器 | `@ct.event(ct.GameEvent.HallLoginEnd)` | `Template/event/GameEvent.ts` |
| 跳转码 | `@ct.jump(code)` | `Template/decorator/JumpDecorator.ts` |
