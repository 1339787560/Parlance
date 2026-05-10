# L1 UI 组件模块

## 模块职责

负责游戏界面渲染、用户交互、动画效果。

## 主要文件路径

```
assets/game/scripts/components/
├── Game.ts              # 主游戏组件
├── HandCard.ts          # 手牌组件
├── BaseCard.ts          # 牌基类组件
├── CPGCard.ts           # 吃碰杠单牌
├── CPGCards.ts          # 吃碰杠牌组
├── CPGCardsUnit.ts      # 吃碰杠牌单元
├── ChooseCard.ts        # 选牌组件
├── ChooseCardUnit.ts    # 选牌单元
├── CastOffCard.ts       # 出牌组件
├── PlayerNode.ts        # 玩家节点
├── PlayerInfoNode.ts    # 玩家信息节点
├── AudioSound.ts        # 音效管理
├── CardCatchAni.ts      # 抓牌动画
├── AniGameStart.ts      # 游戏开始动画
└── WifiAndTime.ts       # 网络和时间显示
```

## 组件层级结构

```
Game (主场景)
├── bgNode (背景)
├── PlayerNode[] (玩家节点)
│   ├── PlayerInfoNode (玩家信息)
│   ├── HandCard (手牌)
│   └── CPGCards (吃碰杠牌)
├── ChooseCard (选牌区)
├── CastOffCard (出牌区)
└── OperateBtns (操作按钮)
```

## 核心组件解析

### HandCard.ts

**职责**: 手牌显示与交互

**核心功能**:
- 手牌排列显示
- 选牌高亮
- 出牌动画
- 换三张选择

### CPGCards.ts

**职责**: 吃碰杠牌组显示

**核心功能**:
- 碰牌组显示
- 杠牌组显示
- 暗杠隐藏逻辑
- 动画效果

### PlayerInfoNode.ts

**职责**: 玩家信息展示

**显示内容**:
- 头像
- 昵称
- 分数
- 状态标识 (听牌、离线等)

### AudioSound.ts

**职责**: 音效管理

**音效类型**:
- 出牌音效
- 吃碰杠胡音效
- 背景音乐
- 系统提示音

## 动画系统

### AnimationPlayer.ts

**职责**: 动画播放控制

**动画类型**:
- 发牌动画
- 出牌动画
- 吃碰杠动画
- 胡牌特效

### CardCatchAni.ts

**职责**: 抓牌动画

**流程**:
```
牌从牌堆飞出
    │
    ▼
移动到玩家位置
    │
    ▼
翻牌显示
```

## 屏幕适配

### AdaptSafeArea.ts

**职责**: 安全区域适配

**适配逻辑**:
- 刘海屏适配
- 底部安全区
- 横竖屏切换

## 交互事件

### NodeTouch.ts

**职责**: 节点触摸事件处理

**事件类型**:
- 点击
- 长按
- 滑动

## 3D 子系统（L2 深读）

| 子系统 | 文档 | 说明 |
|--------|------|------|
| 3D 牌桌 | [L2_3DGameDesk.md](L2_3DGameDesk.md) | GameDeskManager、ClockManager、DicesManager、摄像机适配 |
| 3D 手牌 | [L2_3DHandCards.md](L2_3DHandCards.md) | HandCard→HandCards→HandCardsManager 层级、发牌/出牌流程 |
| 胡牌动效 | [L2_HuEffect.md](L2_HuEffect.md) | HuTypeConfigs 优先级算法、特效播放、粒子动画 |

## 注意事项

1. **节点缓存**: 使用 `SimpleNodePools` 管理节点池
2. **性能优化**: 避免频繁创建销毁节点
3. **资源释放**: 离开场景时释放资源
