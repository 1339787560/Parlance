# L2 游戏事件系统详解

## 概述

游戏事件系统基于观察者模式，实现模块间解耦通信。核心组件包括事件中心、事件定义、事件组件装饰器。

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                     事件系统架构                              │
├─────────────────────────────────────────────────────────────┤
│  eventCenter (单例)                                         │
│      │                                                      │
│      ├── emit(event, ...args) → 发送事件                    │
│      │                                                      │
│      ├── on(event, callback, target) → 监听事件             │
│      │                                                      │
│      └── off(event, callback, target) → 取消监听            │
│                                                             │
│  @event 装饰器                                               │
│      │                                                      │
│      └── 自动绑定事件监听                                    │
│                                                             │
│  @eventComponent 装饰器                                      │
│      │                                                      │
│      └── 组件销毁时自动解绑                                  │
└─────────────────────────────────────────────────────────────┘
```

## 文件结构

```
assets/game/scripts/event/
├── callbacks-invoker.ts    # 回调调用器
├── event-component.ts      # 事件组件装饰器
├── eventify.ts             # 事件化封装
├── events-cache.ts         # 事件缓存
├── game-event.ts           # 游戏事件定义
└── game-eventcenter.ts     # 事件中心单例
```

## 核心事件定义 (GameEvent)

### 应用生命周期

| 事件名 | 触发时机 |
|--------|----------|
| `Canvas_Resize` | 屏幕尺寸变化 |
| `onAppPause` | 应用暂停 (后台) |
| `onAppResume` | 应用恢复 (前台) |

### 游戏流程

| 事件名 | 触发时机 |
|--------|----------|
| `onEnterGameOK` | 进入游戏成功 |
| `onGameDXXW` | 断线重连 |
| `onWaitNewTable` | 等待匹配 |
| `onPlayerStartGame` | 玩家点击准备 |
| `onGameStart` | 游戏开始 |
| `onDealCardFinished` | 发牌结束 |

### 玩家状态

| 事件名 | 触发时机 |
|--------|----------|
| `onPlayerEnter` | 玩家进入 |
| `onPlayerAbort` | 玩家退出 |
| `onPlayerOffline` | 玩家断线 |
| `onPlayerOnline` | 玩家重连 |
| `onPlayerKickOut` | 玩家被踢 |
| `onUpdateThirdInfo` | 第三方信息变更 |

### 牌局操作

| 事件名 | 触发时机 |
|--------|----------|
| `onCardsThrow` | 出牌 |
| `onCardCaught` | 摸牌 |
| `onCardChi` | 吃牌 |
| `onCardPeng` | 碰牌 |
| `onCardMnGang` | 明杠 |
| `onCardAnGang` | 暗杠 |
| `onCardPnGang` | 碰杠 |
| `onCardHua` | 补花 |
| `onCardGuo` | 过牌 |

### 操作响应

| 事件名 | 触发时机 |
|--------|----------|
| `rspThrowCards` | 出牌响应 |
| `rspCatchCard` | 摸牌响应 |
| `rspChiCard` | 吃牌响应 |
| `rspPengCard` | 碰牌响应 |
| `rspMnGangCard` | 明杠响应 |
| `rspAnGangCard` | 暗杠响应 |
| `rspPnGangCard` | 碰杠响应 |

### 定缺流程

| 事件名 | 触发时机 |
|--------|----------|
| `rspDingque` | 定缺操作响应 |
| `onDingqueFinished` | 定缺结束 |
| `onConfirmDingQue` | 确认定缺 |

### 托管系统

| 事件名 | 触发时机 |
|--------|----------|
| `onStartAutoPlay` | 主动触发托管 |
| `onCancelAutoPlay` | 主动取消托管 |
| `onAutoPlayStarted` | 托管启动成功 |
| `onAutoPlayCanceled` | 托管取消成功 |

## 装饰器使用

### @event 装饰器

```typescript
@eventComponent
@ccclass('PlayerManager')
export class PlayerManager extends Component {
    
    // 自动监听，组件销毁时自动解绑
    @event(GameEvent.onPlayerEnter)
    @event(GameEvent.onPlayerAbort)
    protected event_onUpdatePlayerNode(chairNo: number) {
        this.updatePlayerNode(chairNo);
    }
    
    @event(GameEvent.onGameStart)
    protected event_onGameStart() {
        for (let i = 0; i < GameInfo.getTotalChairs(); i++) {
            this.updatePlayerNode(i);
        }
    }
}
```

### 手动监听

```typescript
import eventCenter from '../event/game-eventcenter';
import { GameEvent } from '../event/game-event';

// 发送事件
eventCenter.emit(GameEvent.onGameStart);

// 监听事件
eventCenter.on(GameEvent.updateCardRecord, this.onUpdateCardRecord, this);

// 取消监听
eventCenter.off(GameEvent.updateCardRecord, this.onUpdateCardRecord, this);
```

## 事件流示例

### 出牌流程

```
玩家点击出牌
    │
    ▼
Game.ts: onClickCard()
    │
    ▼
GameConnect.send(出牌请求)
    │
    ▼
服务器处理
    │
    ▼
GameConnect.onMessage()
    │
    ▼
eventCenter.emit(GameEvent.rspThrowCards)
    │
    ▼
┌──────────────┬──────────────┐
│              │              │
▼              ▼              ▼
PlayerManager  HandCard      OperateBtnsManager
更新玩家状态   更新手牌       更新按钮
```

### 断线重连流程

```
检测到断线
    │
    ▼
GameConnect.reconnect()
    │
    ▼
服务器返回游戏状态
    │
    ▼
GameInfo.restoreState()
    │
    ▼
eventCenter.emit(GameEvent.onGameDXXW)
    │
    ▼
┌──────────────┬──────────────┬──────────────┐
│              │              │              │
▼              ▼              ▼              ▼
PlayerManager  HandCard      TableInfo     StartManager
恢复玩家头像   恢复手牌       恢复桌面       恢复状态
```

## 事件命名规范

| 前缀 | 含义 |
|------|------|
| `on` | 状态变化通知 |
| `rsp` | 服务器响应 |
| `LC` | 本地消息 (Local) |

## Known Issues / 避坑指南

### [2024-04] 内存泄漏风险

- **现象**: 组件销毁后事件监听未移除
- **解决方案**: 使用 `@eventComponent` 装饰器自动解绑

### [2024-04] 事件参数顺序

- **现象**: emit 和 on 的参数不匹配
- **解决方案**: 参考事件定义，确保参数顺序一致

### [2024-04] 循环触发

- **现象**: 事件处理中再次 emit 同事件导致死循环
- **解决方案**: 使用 `onCardGuoEveryPlayer` 等广播事件时避免重复触发