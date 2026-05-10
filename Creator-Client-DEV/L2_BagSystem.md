# L2 背包系统详解

## 概述

背包系统管理玩家所有道具和装饰品，支持道具使用、装饰穿戴、数据同步等功能。

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                     背包系统架构                              │
├─────────────────────────────────────────────────────────────┤
│  BagPlugin (插件入口)                                        │
│      │                                                      │
│      ├── onInit() → 拉取配置、注册视图                       │
│      │                                                      │
│      ├── onDataReducer() → 状态管理                         │
│      │                                                      │
│      └── onMount() → 嵌入UI节点                              │
│                                                             │
│  BagNotify (通知处理)                                        │
│      │                                                      │
│      ├── ntfRewardMessage() → 道具增加通知                   │
│      │                                                      │
│      ├── ntfConsumPropMessage() → 道具消耗通知               │
│      │                                                      │
│      └── ntfUseEffectMessage() → 装饰穿戴通知                │
└─────────────────────────────────────────────────────────────┘
```

## 数据结构

### 道具数据 (BagItem)

```typescript
interface BagItem {
    propId: number;      // 道具ID
    propCount: number;   // 道具数量
    endTime: number;     // 时效道具到期时间
}
```

### 装饰数据 (UserEffect)

```typescript
interface UserEffect {
    tab: number;        // 装饰分类标签
    group: number;      // 装饰分组
    propId: number;     // 装饰道具ID
    // ...其他属性
}
```

## 服务器通知消息

### 通知消息ID

| 消息ID | 用途 |
|--------|------|
| `PB_NOTIFY__NTF_REWARD` | 奖励通知 (道具增加) |
| `PB_NOTIFY__NTF_CONSUMPROP` | 消耗道具通知 |
| `PB_NOTIFY__NTF_USEREFFECT` | 使用装饰通知 |

### 道具增加处理流程

```typescript
static ntfRewardMessage(data) {
    let notifyData = ct.deserializepb(data, "BagPB.NotifyReward");
    
    // 1. 更新背包数据
    this.updateBagData(notifyData.prop);
    
    // 2. 分发事件
    ct.btreeCenter.runAction("Action_EmitEvent", null, {event:"UpdateBagData"});
    
    // 3. 触发延迟刷新
    this.triggerRefresh();
}
```

### 道具消耗处理流程

```typescript
static ntfConsumPropMessage(data) {
    let notifyData = ct.deserializepb(data, "BagPB.NotifyConsumProp");
    
    // 构造负数数量
    let item = {
        propId: notifyData.propId,
        propCount: -notifyData.propCount,
        endTime: 0
    };
    
    this.updateBagData(item);
}
```

## 数据更新逻辑

### updateBagData 核心逻辑

```typescript
private static updateBagData(data: BagItem) {
    let bagState = this.dataCenter.getState(ct.PluginType.Bag);
    let arrayData = bagState?.get(ct.DataType.BagData) || [];
    
    // 获取道具配置
    let itemCfg = ct.propItemsConfig.getPropById(data.propId);
    let consummode = itemCfg?.consummode || ct.PROP_CONSUMMODE.MULTIPLE;
    
    // 根据消耗模式处理
    switch(consummode) {
        case ct.PROP_CONSUMMODE.TIMING:
            // 时效类道具刷新时间
            element.endTime = data.endTime;
            break;
            
        case ct.PROP_CONSUMMODE.MULTIPLE:
        case ct.PROP_CONSUMMODE.PERIOD:
            // 数量类道具增减数量
            element.propCount += data.propCount;
            break;
    }
    
    // 通知数据中心
    this.dataCenter.dispatch({
        type: BagConfig.ReducerActionTypes.AT_BagItemArray, 
        value: arrayData
    });
}
```

### 道具消耗模式

| 模式 | 说明 |
|------|------|
| `TIMING` | 时效类道具 (按到期时间) |
| `MULTIPLE` | 多次使用道具 (按数量) |
| `PERIOD` | 周期性道具 |

## 装饰穿戴逻辑

### updateEffectData 核心逻辑

```typescript
private static updateEffectData(data: BagPB.NotifyUseEffect) {
    let arrayEffects = bagState?.get(ct.DataType.UserEffects) || [];
    let state = data.state;
    let effect = data.effect;
    
    // 查找同组装饰
    for (let i = 0; i < arrayEffects.length; i++) {
        if (element.tab == effect.tab && element.group == effect.group) {
            if (state == BagConfig.EffectState.EOn) {
                // 穿戴: 替换
                arrayEffects.splice(i, 1, effect);
            } else {
                // 卸下: 移除
                arrayEffects.splice(i, 1);
            }
            break;
        }
    }
    
    // 新穿戴
    if (!isFind && state == BagConfig.EffectState.EOn) {
        arrayEffects.push(effect);
        
        // 自动装饰桌布
        ct.btreeCenter.runAction("Action_AutoChangeDeskBg", null, {effect: effect});
    }
    
    // 通知更新
    this.dataCenter.dispatch({
        type: BagConfig.ReducerActionTypes.AT_UserEffectArray, 
        value: arrayEffects
    });
}
```

### 装饰状态

| 状态 | 说明 |
|------|------|
| `EOn` | 穿戴中 |
| `EOff` | 已卸下 |

## 特殊业务逻辑

### 新增装饰自动穿戴

```typescript
// 策划需求：新增装饰类道具，需要自动装饰
private static addRedPoint(data: BagItem) {
    let itemCfg = ct.propItemsConfig.getPropById(data.propId);
    
    // 只处理装饰类道具
    if (itemCfg.sub_type != ct.PROP_SUBTYPE.EFFECT) return;
    
    // 增加小红点
    ct.unReadCenter.addUnReadFlag(BagConfig.RedDot.RP_BagEffect);
    
    // 自动使用新装饰
    ct.btreeCenter.runAction("Action_UseProp", null, {propId: data.propId});
}
```

### 预加载装饰预制体

```typescript
preLoadDecoratePrefab() {
    let effectArr = this.dataCenter.getState(ct.PluginType.Bag).get(ct.DataType.UserEffects);
    
    for (let effect of effectArr) {
        if (PreloadDecorateType.indexOf(effect.group) != -1 && effect.propId != 0) {
            let prop = ct.propItemsConfig.getPropById(effect.propId);
            if (prop?.param?.effect['prefabPath']) {
                ct.PrefabCache.getPrefab(prop.param.effect['prefabPath']);
            }
        }
    }
}
```

## 延迟刷新机制

```typescript
// 道具变化后3秒重新拉取数据，防止数据不一致
private static triggerRefresh() {
    if (BagNotify.tickEntry) {
        clearTimeout(BagNotify.tickEntry);
    }
    
    BagNotify.tickEntry = setTimeout(() => {
        ct.btreeCenter.runAction("Action_GetBagList");
    }, 3000);
}
```

## Known Issues / 避坑指南

### [2024-04] 相同装扮自动卸下

- **现象**: 新获取的装饰与已穿戴装饰同组时，需先卸下原装饰
- **处理**: 自动执行卸下→穿戴流程

### [2024-04] 数据不一致

- **现象**: 服务器推送与本地数据不同步
- **解决方案**: 3秒后自动重新拉取数据

### [2024-04] 时效道具过期判断

- **现象**: 时效道具可能在客户端显示未过期但服务器已过期
- **解决方案**: 更新时检查 `endTime <= ct.CommonFunc.getServerTime()`
