# L2 3D牌桌系统详解

## 概述

3D牌桌系统负责游戏场景的渲染和管理，包括牌桌、骰子、时钟、摄像机等元素。支持3D/2D双模式切换，适配鸿蒙设备。

## 文件结构

```
assets/game/plugins/gamedesk/scripts/
├── GameDeskManager.ts          # 牌桌管理器 (主入口)
├── TableManager.ts             # 桌面管理器
├── ClockManager.ts             # 时钟管理器
├── DicesManager.ts             # 骰子管理器
├── ChooseCardUnitsManager3D.ts # 3D选牌管理器
└── CameraAdjuster.ts           # 摄像机调节器
```

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                     3D牌桌系统架构                            │
├─────────────────────────────────────────────────────────────┤
│  GameDeskManager (继承 GameSceneManager)                    │
│      │                                                      │
│      ├── HandCardsManager (手牌区)                          │
│      │                                                      │
│      ├── CastoffCardsManager (废牌区)                       │
│      │                                                      │
│      ├── FlowerCardsManager (花牌区)                        │
│      │                                                      │
│      ├── HuCardsManager (胡牌区)                            │
│      │                                                      │
│      ├── ClockManager (时钟)                                │
│      │                                                      │
│      └── DicesManager (骰子)                                │
│                                                             │
│  场景切换                                                    │
│      │                                                      │
│      ├── 3D模式: 显示 Node_Table                            │
│      │                                                      │
│      └── 2D模式 (鸿蒙): 隐藏 Node_Table                     │
└─────────────────────────────────────────────────────────────┘
```

## GameDeskManager (牌桌管理器)

**职责**: 游戏场景总管，协调各子管理器

**核心属性**:

| 属性 | 类型 | 用途 |
|------|------|------|
| `handCardsManager` | HandCardsManager | 玩家手牌区 |
| `costoffCardsManager` | CastoffCardsManager | 玩家废牌区 |
| `flowerCardsManager` | FlowerCardsManager | 玩家花牌区 |
| `huCardsManager` | HuCardsManager | 玩家胡牌区 |

**平台适配**:

```typescript
// 鸿蒙设备切换到2D牌桌
adjustTableDimensionForHarmony() {
    if (sys.os !== sys.OS.OHOS) {
        // 非鸿蒙: 显示3D牌桌
        tableNode.active = true;
    } else {
        // 鸿蒙: 隐藏3D牌桌，使用2D
        tableNode.active = false;
    }
}
```

**屏幕适配**:

```typescript
updateArea() {
    let fromRatio = 720 / 1280;  // 设计比例
    let curRatio = vs.height / vs.width;
    let factor = curRatio / fromRatio;
    
    if (factor > 1) {
        // 调整摄像机FOV
        this._perspCamera.fov = 16 * factor;
        // 缩放手牌区域
        this.handCardsManager.getEntryByDrawIndex(myDrawIndex)
            .node.setScale(1 / factor, 1 / factor, 1);
    }
}
```

## ClockManager (时钟管理器)

**职责**: 游戏倒计时显示

**核心功能**:
- 显示当前玩家操作倒计时
- 倒计时结束提醒
- 超时处理

## DicesManager (骰子管理器)

**职责**: 骰子动画和控制

**核心功能**:
- 播放骰子投掷动画
- 显示骰子结果
- 触发发牌流程

## ChooseCardUnitsManager3D (3D选牌管理器)

**职责**: 管理3D模式下的吃碰杠牌组选择

**核心功能**:
- 显示可选的吃牌组合
- 显示可选的杠牌组合
- 处理玩家选择

## 摄像机系统

### CameraAdjuster

**职责**: 摄像机参数调节

**核心参数**:
- FOV (视场角)
- 位置
- 旋转角度

## 场景层级结构

```
GameDesk (根节点)
├── Node_Table (3D牌桌)
│   ├── 桌面模型
│   ├── 椅子模型
│   └── 装饰物
├── HandCardsArea (手牌区域)
│   ├── Player1Cards
│   ├── Player2Cards
│   ├── Player3Cards
│   └── Player4Cards
├── CastoffArea (废牌区域)
├── Clock (时钟)
└── Cameras (摄像机组)
    ├── PerspectiveCamera (透视)
    └── OrthoCamera (正交)
```

## 初始化流程

```
GameDeskManager.onLoad()
    │
    ├── adjustTableDimensionForHarmony()  // 平台适配
    │
    └── super.onLoad()  // GameSceneManager 初始化
        │
        ├── 初始化各子管理器
        │
        └── 绑定事件监听
```

## 测试系统

**内置测试按键** (测试环境):

```typescript
test(event: EventKeyboard) {
    // 数字键1: 设置手牌
    if (eventKey == KeyCode.DIGIT_1) {
        this.handCardsManager.setHandCards(drawIndex, 13, HandCards, true, true);
    }
    // 数字键2: 添加废牌
    else if (eventKey == KeyCode.DIGIT_2) {
        this.CostoffCardsManager.addCard(drawIndex, cardId);
    }
}
```

## 与其他模块的交互

```
GameDeskManager
    │
    ├── 监听 GameEvent
    │   ├── onGameStartAniFinished → 开始发牌
    │   └── onCanvas_Resize → 屏幕适配
    │
    ├── 协调 HandCardsManager
    │   └── 手牌操作、选牌、出牌
    │
    └── 协调 CastoffCardsManager
        └── 废牌动画、出牌落点
```

## Known Issues / 避坑指南

### [2024-04] 鸿蒙设备适配

- **现象**: 鸿蒙设备3D性能不佳
- **解决方案**: 检测 `sys.OS.OHOS`，切换到2D牌桌

### [2024-04] 屏幕比例异常

- **现象**: 非标准屏幕比例下手牌显示异常
- **解决方案**: 动态调整摄像机FOV和手牌缩放

### [2024-04] 节点有效性检查

- **现象**: 场景切换时节点可能已销毁
- **解决方案**: 操作前检查 `isValid`
