# L2 3D手牌系统详解

## 概述

3D手牌系统负责麻将游戏中所有牌张的渲染、动画和交互。采用分层架构，从单张牌到牌组再到管理器，逐层抽象。

## 文件结构

```
assets/game/plugins/gamecards/scripts/
├── common/
│   ├── BaseCard.ts           # 牌基类
│   ├── BaseCards.ts          # 牌组基类
│   └── BaseCardsManager.ts   # 牌组管理器基类
├── handcards/
│   ├── HandCard.ts           # 单张手牌
│   ├── HandCards.ts          # 手牌组
│   ├── HandCardsManager.ts   # 手牌管理器
│   ├── CardTips.ts           # 牌提示
│   └── ShowHandCardsManager.ts # 展示手牌管理器
├── castoffcards/             # 废牌区
├── cpgcards/                 # 吃碰杠牌区
├── hucards/                  # 胡牌区
├── throwcards/               # 出牌区
└── flowercards/              # 花牌区
```

## 核心类架构

```
┌─────────────────────────────────────────────────────────────┐
│                     手牌系统层级                              │
├─────────────────────────────────────────────────────────────┤
│  HandCardsManager (管理器层)                                │
│      │                                                      │
│      ├── 管理多个玩家的手牌区域                              │
│      ├── 监听游戏事件，分发到对应 HandCards                  │
│      └── 协调手牌、废牌、胡牌等区域                          │
│                                                             │
│  HandCards (牌组层)                                          │
│      │                                                      │
│      ├── 管理单玩家的所有手牌                                │
│      ├── 包含 catchcard (抓牌) 节点                         │
│      └── 提供选牌、发牌、排序等操作                          │
│                                                             │
│  HandCard (单牌层)                                           │
│      │                                                      │
│      ├── 单张牌的渲染和交互                                  │
│      ├── 支持选中、提起、听牌标记                            │
│      └── 处理触摸事件                                        │
└─────────────────────────────────────────────────────────────┘
```

## 核心类详解

### HandCardsManager (手牌管理器)

**职责**: 管理所有玩家的手牌区域，响应游戏事件

**主要方法**:

| 方法 | 用途 |
|------|------|
| `processDealCards()` | 发牌流程 |
| `setHandCards()` | 设置手牌 |
| `onDealCardFinished()` | 发牌结束回调 |
| `_setCatchCard()` | 设置抓牌 |
| `ope_BuildExchange3Cards()` | 构建换三张提示 |

**关键事件监听**:

```typescript
@event(GameEvent.onGameStartAniFinished)  // 游戏开始动画结束，开始发牌
@event(GameEvent.onSelectRecommendExchangeCard)  // 选择推荐换牌
@event(GameEvent.onFrdGameAbort)  // 好友房结束
```

### HandCards (手牌组)

**职责**: 管理单个玩家的手牌

**核心属性**:

| 属性 | 类型 | 用途 |
|------|------|------|
| `catchcard` | HandCard | 抓牌节点 |
| `sortoffset` | number | 理牌偏移高度 |
| `_lastSelectItem` | HandCard | 上次选中的牌 |

**核心方法**:

```typescript
// 显示手牌
showHandCards(cardsCount: number, canSelected: boolean, cardIDs?: number[])

// 获取选中牌
getSelectCards(): number[]

// 选牌
selectHandCards(cardIds: number[])

// 取消选牌
onUnSelectdCards(exceptCards?: number[], needAni?: boolean)

// 开始发牌动画
startDealCards(cardIDs: number[]): Promise<void>

// 设置手牌角标 (缺、癞)
setHandcardsMark()
```

### HandCard (单张手牌)

**职责**: 单张牌的渲染、交互、状态管理

**核心属性**:

| 属性 | 类型 | 用途 |
|------|------|------|
| `selectOffset` | number | 选中提起距离 |
| `nodeLight` | Node | 高亮标记节点 |
| `nodeFire` | Node | 胡牌火焰节点 |
| `bTouchEn` | boolean | 是否可点击 |
| `prefabTips` | Prefab | 听牌提示预制体 |

**听牌标签类型**:

```typescript
export const TingCardType = {
    CARD_TING_TYPE_NORMAL: 0,       // 正常标签
    CARD_TING_TYPE_DA: 1,           // 标签"大"
    CARD_TING_TYPE_DUO: 2,          // 标签"多"
    CARD_TING_TYPE_DA_DUO: 3,       // 大和多标签
    CARD_TING_TYPE_RECOMMEND: 4,    // 牌型标签
    CARD_TING_TYPE_COUQYS: 5,       // 凑牌标签
    CARD_TING_TYPE_QUE: 6,          // 缺牌标签
}
```

**核心方法**:

```typescript
// 设置牌ID
setCardIdWithShow(cardId: number, showFront: boolean, showAni: boolean)

// 设置角标
setCardMark()

// 选中/取消选中
setSelected(select: boolean, needAni?: boolean)

// 胡牌火焰
freshFire(show: boolean)
```

## 发牌流程

```
GameEvent.onGameStartAniFinished
    │
    ▼
HandCardsManager.event_startDealCard()
    │
    ▼
processDealCards()
    │
    ├── 获取所有玩家手牌数量
    │
    ├── 自己: 排序后的牌ID数组
    │
    └── 其他玩家: 全0数组(显示背面)
    │
    ▼
Promise.all([各玩家 startDealCards()])
    │
    ▼
onDealCardFinished(catchID)
    │
    ▼
_setCatchCard(nBankIndex, catchID)  // 庄家抓牌
```

## 出牌流程

```
玩家点击手牌
    │
    ▼
HandCard 触摸事件
    │
    ├── EVENT_NODE_THROW → 出牌
    │
    ├── EVENT_NODE_CANCEL → 取消
    │
    └── EVENT_NODE_MOVE → 移动
    │
    ▼
HandCards.onThrowCards()
    │
    ▼
返回 IHandCardsThrowInfo
    │
    ▼
GameDeskManager 抛给 CastoffCardsManager
```

## 数据接口

### IHandCardsThrowInfo (出牌信息)

```typescript
export interface IHandCardsThrowInfo {
    cardID: number;      // 牌ID
    item: HandCard;      // 牌对象
    cardpos: number;     // 牌位置
    worldPos: Vec3;      // 牌世界坐标
}
```

## 手牌池机制

```typescript
const HAND_CARDS_POOL_SIZE = 14;  // 池最大容量

// 获取空闲牌节点
getFreeCardUnitNode(): Node

// 归还牌节点到池
clearNode(node: Node)
```

## Known Issues / 避坑指南

### [2024-04] 手牌池耗尽

- **现象**: 牌池用完导致崩溃
- **解决方案**: 检测到异常时调用 `ct.mjGameCenter?.refreshTableInfo()` 刷新

### [2024-04] 抓牌动画时机

- **现象**: 发牌时抓牌和手牌冲突
- **解决方案**: 发牌时将抓牌从手牌数组中移除，发牌结束再设置

### [2024-04] 听牌标记清除

- **现象**: 游戏结束时听牌标记未清除
- **解决方案**: 在 `setCardMark()` 中检查 `GameInfo.isGameRunning()`
