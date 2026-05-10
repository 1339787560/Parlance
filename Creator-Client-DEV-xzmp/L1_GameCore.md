# L1 核心游戏逻辑模块

## 模块职责

负责游戏场景的生命周期管理、玩家状态同步、牌局流程控制。

## 主要文件路径

```
assets/game/scripts/
├── components/
│   ├── Game.ts              # 主游戏控制器 (168KB)
│   ├── HandCard.ts          # 手牌管理
│   ├── BaseCard.ts          # 牌基类
│   ├── CPGCards.ts          # 吃碰杠牌组
│   ├── PlayerNode.ts        # 玩家节点
│   └── PlayerInfoNode.ts    # 玩家信息节点
├── manager/
│   ├── PlayerManager.ts     # 玩家管理器
│   ├── TableInfoManager.ts  # 桌面信息管理
│   ├── StartManager.ts      # 开始流程管理
│   ├── ResultManager.ts     # 结算管理
│   └── OperateBtnsManager.ts # 操作按钮管理
└── event/
    ├── game-event.ts        # 游戏事件定义
    └── game-eventcenter.ts  # 事件中心
```

## 核心类解析

### Game.ts (主控制器)

**职责**: 游戏场景入口，协调各管理器

**关键属性**:
- `theGame`: 全局单例引用
- `bgNode`: 背景节点
- `btnTest`: 测试按钮

**生命周期**:
1. `onLoad()`: 初始化游戏配置、事件监听
2. `onEnable()`: 屏幕适配监听
3. `onceAdapt()`: 鸿蒙屏幕适配

### PlayerManager.ts

**职责**: 管理所有玩家状态

**核心功能**:
- 玩家座位管理
- 玩家状态同步
- 玩家信息更新

### TableInfoManager.ts

**职责**: 桌面信息管理

**核心功能**:
- 桌面状态维护
- 牌局进度追踪
- 公共信息展示

## 游戏流程

```
进入游戏
    │
    ▼
Init.ts → 物理系统初始化
    │
    ▼
Game.onLoad() → 场景加载
    │
    ▼
StartManager → 开始流程
    │
    ▼
牌局进行中 → PlayerManager/TableInfoManager
    │
    ▼
ResultManager → 结算展示
```

## 事件系统

### 核心事件 (GameEvent)

| 事件名 | 触发时机 |
|--------|----------|
| updateCardRecord | 更新牌局记录 |
| playerEnter | 玩家入场 |
| playerLeave | 玩家离场 |
| gameStart | 游戏开始 |
| gameOver | 游戏结束 |

### 使用方式

```typescript
// 发送事件
eventCenter.emit(GameEvent.updateCardRecord);

// 监听事件
eventCenter.on(GameEvent.gameStart, this.onGameStart, this);
```

## 业务术语

| 术语 | 含义 |
|------|------|
| CPG | 吃(Peng)、碰(Chi)、杠(Gang) |
| 手牌 | 玩家手中的牌 |
| 出牌 | 打出一张牌 |
| 听牌 | 等待胡牌状态 |
