# L1 插件架构 — Creator 客户端

## 概述

客户端业务功能采用插件化架构，遵循统一的 **Plugin → ViewCtrl → Help → View → Def** 五层模式。每个功能模块作为独立插件存在，具有独立的生命周期、状态管理和视图系统。

## 标准文件结构

```
assets/plugins/<name>/
├── prefabs/
│   ├── <Name>View.prefab       # 主界面预制体
│   └── <Name>Node.prefab       # 入口节点预制体
├── scripts/
│   ├── <Name>Plugin.ts          # 插件主类
│   ├── <Name>Def.ts             # 常量定义
│   ├── <Name>Help.ts            # 工具函数
│   ├── <Name>ViewCtrl.ts        # 视图控制器
│   └── view/
│       ├── <Name>View.ts        # 主界面视图
│       └── <Name>NodeView.ts    # 入口节点视图
```

## 1. Plugin — 插件主类

继承 `ct.BasePlugin`，被模块管理器直接管理。使用 `@ct.plugin` 装饰器声明。

### 核心职责

| 方法 | 职责 |
|------|------|
| `onInit()` | 注册视图、监听 CP 通知、拉取配置（返回 Promise） |
| `onDestroy()` | 移除通知回调 |
| `onDataReducer(state, action)` | Redux 模式状态管理，dispatch 后自动触发 |
| `checkSupported()` | 判断插件是否可用，决定是否展示 Node/View |
| `checkPopupCondition(viewName, conditionType)` | 弹窗条件检查（`checkSupported` 为 true 才触发） |
| `onMount(slot, container)` | 挂载到插槽，加载入口节点 |

### 示例

```typescript
@ccclass('ShakePlugin')
@ct.plugin
export class ShakePlugin extends ct.BasePlugin {

    onInit() {
        ct.centerCtrl.addPopupView(this, "ShakeSelectView", {
            prefabPath: "prefabs/ShakeSelectView",
            backgroundType: ct.ViewBackgroundType.Gray,
            bTouchClose: true
        });

        this.notifySocket.addHandler(
            ct.CommonGiftInterFace.NotifyMsgID.NTF_COMMONGIFT_EXCHANGEOK,
            this.ntfExchangeOKMessage.bind(this)
        );

        return new Promise<void>((resolve, reject) => {
            this.queryConfig().then(() => resolve()).catch(() => reject());
        });
    }

    onDestroy() {
        this.notifySocket.delHandler(ct.CommonGiftInterFace.NotifyMsgID.NTF_COMMONGIFT_EXCHANGEOK);
    }

    onDataReducer(state: ct.StateRead, action: ct.AnyAction) {
        if (!state) {
            return {
                [Def.DataType.GiftInfo]: null,
                [Def.DataType.FreeCount]: 0,
            };
        }
        switch (action.type) {
            case Def.ReduceType.UpdateGift:
                return { [Def.DataType.GiftInfo]: action.value };
            case Def.ReduceType.UpdateFreeCount:
                return { [Def.DataType.FreeCount]: action.value };
        }
    }

    checkSupported(): boolean {
        let moduleInfo = this.dataCenter.getState(Def.PluginName).get(Def.DataType.ModuleInfo);
        return moduleInfo
            ? ct.CommonGiftInterFace.isModuleEnable(moduleInfo, ct.CommonGiftInterFace.MODULES.SHAKEGIFT)
            : false;
    }

    @ct.event(ct.GameEvent.HallLoginEnd)
    event_onHallLoginEnd() { /* 大厅登录后更新数据 */ }

    @ct.jump(22)  // 跳转码
    onGoto(gotoType: number) {
        ct.centerCtrl.informPluginViewByName(Def.PluginName, {
            viewName: "ShakeSelectView", source: "WebActivityClick"
        });
    }
}
```

## 2. ViewCtrl — 视图控制器

继承 `ct.BaseViewCtrl`，负责数据源管理、动作处理和跨插件通信。

```typescript
@ccclass('ShakeViewCtrl')
export class ShakeViewCtrl extends ct.BaseViewCtrl {

    createDataSource(createParams): ct.ViewDataSource {
        let dataSource = new ct.ViewDataSource();
        let freeCount = this.dataCenter.getState(Def.PluginName)
            .getNumber(Def.DataType.FreeCount);
        dataSource.add("freecount", { count: freeCount });
        dataSource.add("shakegift", { shake: 0 });
        return dataSource;
    }

    onRequest(action: ct.AnyAction) {
        switch (action.type) {
            case Def.ActionType.ShakeBegin: this.onShakeBegin(); break;
            case Def.ActionType.BuyGift:    this.onBuyGift();    break;
        }
    }

    onRemove() { /* 界面关闭时清理 */ }
}
```

### 跨插件通信

```typescript
// 向指定 ViewCtrl 发送动作
ct.centerCtrl.postAction(ShakeViewCtrl, { type: Def.ActionType.CloseGift, value: false });
// 或通过插件名称字符串
ct.centerCtrl.postAction("ShakePlugin", { type: Def.ActionType.ShakeBegin });
```

## 3. Help — 工具函数类

继承 `ct.BaseFunctionNode`，提供便捷的数据访问和修改能力。方法使用 `static` 声明。

```typescript
@ccclass('ShakeHelp')
export class ShakeHelp extends ct.BaseFunctionNode {

    public static isCanShake(): boolean {
        let freeCount = this.dataCenter.getState(Def.PluginName)
            .getNumber(Def.DataType.FreeCount);
        return freeCount > 0 && !this.hasValidGift();
    }

    public static hasValidGift(): boolean {
        let giftInfo = this.dataCenter.getState(Def.PluginName)
            .get(Def.DataType.GiftInfo);
        let expireTime = this.dataCenter.getState(Def.PluginName)
            .getNumber(Def.DataType.ExpireTime);
        if (!giftInfo || !expireTime) return false;
        return Math.floor(Date.now() / 1000) < expireTime;
    }
}
```

## 4. View — 视图层

### NodeView（入口节点）

大厅或游戏内插槽的入口节点，点击后唤起主界面。

```typescript
@ccclass('ShakeNodeView')
@ct.viewctrl(ShakeNodeViewCtrl)
export class ShakeNodeView extends ct.BaseView {

    @property({ type: Label, displayName: "剩余次数" })
    label_rstCount: Label = null!;

    onUpdateView(dataSource: ct.ViewDataSourceReadonly) {
        if (dataSource.check("redcount")) {
            this.label_rstCount.string = String(dataSource.get("redcount").count);
        }
    }

    onClick() {
        if (ShakeHelp.hasValidGift() || ShakeHelp.isCanShake()) {
            ct.centerCtrl.informPluginViewByName(Def.PluginName, {
                viewName: "ShakeSelectView",
                source: ct.centerCtrl.isInGame() ? "GameClick" : "HallClick"
            });
        }
    }
}
```

### MainView（主界面）

由数据驱动，随 dataSource 变化自动更新。使用 `onUpdateView(dataSource)` 响应数据变更。

### 容器视图模式

当需要根据状态切换显示不同子页面时使用：

```typescript
checkAndShowView() {
    if (ShakeHelp.hasValidGift()) {
        this.showResultView();  // 领奖页面
    } else {
        this.showShakeView();   // 摇奖页面
    }
}
```

## 5. Def — 常量定义

```typescript
export namespace ShakeDef {
    export const PluginName = "ShakePlugin";

    export const ViewName = {
        ShakeSelectView: "ShakeSelectView",
        ShakeResultView: "ShakeResultView"
    };

    export const DataType = {        // dataCenter 存储键
        GiftInfo: "Shake_GiftInfo",
        FreeCount: "Shake_FreeCount",
    };

    export const ReduceType = {      // dispatch 分发类型
        UpdateGift: "Shake_UpdateGift",
        UpdateFreeCount: "Shake_UpdateFreeCount",
    };

    export const ActionType = {       // postAction 动作类型
        ShakeBegin: "Shake_ShakeBegin",
        BuyGift: "Shake_BuyGift",
    };
}
```

## 数据流转

```
View (用户操作)
  │ postAction({ type: ActionType.XXX })
  ▼
ViewCtrl.onRequest()
  │ this.dataCenter.dispatch({ type: ReduceType.XXX, value })
  ▼
Plugin.onDataReducer()
  │ 更新 DataType 对应的值
  ▼
dataCenter 触发变更通知 → dataSource.bind() 自动同步
  ▼
View.onUpdateView() → 界面刷新
```

## 插槽系统

插件通过插槽嵌入到大厅或游戏内。

| 插槽 | 用途 |
|------|------|
| `Hall_Top` | 大厅顶部信息栏 |
| `Hall_Bottom` | 大厅底部功能栏 |
| `Hall_LeftActivity` | 左侧活动入口 |
| `Game_Top` | 游戏内顶部栏 |
| `Game_Result_Activity` | 结算页活动入口 |

```typescript
let slot = ct.centerCtrl.getPluginSlot(ct.HALL_SLOTS.LEFTACTIVITY);
slot.insertPlugin("PluginName");
slot.removePlugin("PluginName");
```

## 服务端推送处理

所有 CP 脚本推送共用消息号 `2000091002`，通过 `req` 字段区分具体消息类型：

```typescript
export const PB_CP__CLIENT_NOTIFY = 2000091002;

// 注册监听
this.notifySocket.addHandler(PB_CP__CLIENT_NOTIFY, this.onClientNotify.bind(this));

// 根据 req 分发
private onClientNotify(data: any) {
    let info = JSON.parse(ct.Protobuf.ToString(new ct.BinaryStream(data), "UTF8"));
    if (info.req === 'onNewPlayerDailyGiftPurchased') {
        // 处理购买成功推送
    }
}
```

## 常用 API 速查

| 目的 | 调用 |
|------|------|
| 打开插件视图 | `ct.centerCtrl.informPluginViewByName("PluginName", { viewName: "ViewName" })` |
| 关闭视图 | `this.destroy(ct.ViewExitCode.OK)` (ViewCtrl) / `this.destroyView()` (View) |
| 支付 | `ct.payUtils.payForProduct(exchangeid, {}, (code, msg) => {})` |
| 提示信息 | `ct.centerCtrl.showToast(msg)` |
| 奖励弹窗 | `ct.centerCtrl.showRewardDialog([{ propId, propCount }], delay, callback)` |
| 渠道信息 | `ct.CommonFunc.getChannelKey()` |
| 玩家局数 | `ct.LocalCache.getInt("userbout", 0)` |
| 玩法类型 | `(curArea?.extension as any)?.type` |
| 房间等级 | `(curRoom?.extension as any)?.custom?.roomlevel` |

## 最佳实践

### 防重入

View 和 ViewCtrl 层都添加防重入标记：

```typescript
// View 层
doShake() {
    if (this._shaking) return;
    this._shaking = true;
    this.postAction({ type: ActionType.ShakeBegin });
}
// ViewCtrl 层 — 网络回调中重置
this._shaking = false;
```

### 避免重复处理动作

使用唯一 ID 确保每次动作值不同：

```typescript
this._actionId++;
dataSource.getModel("viewaction").set("action", `cleargift_${this._actionId}`);
// View 中: if (action !== this._lastAction) { this._lastAction = action; ... }
```

### 子组件事件通信

```typescript
// 子组件: this.node.emit('shake-click')
// 父组件: this.node.on('shake-click', this.onShakeClick, this)
```

## 参考插件

| 功能类型 | 参考插件 |
|----------|----------|
| 礼包购买 | `shake`, `dressgift`, `joyfulgift`, `resurrect` |
| 月卡 | `cmmonthcard` |
| 支付 | `abtpay`, `shop` |
