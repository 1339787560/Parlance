# L1 麻将算法模块

## 模块职责

负责麻将牌型计算、胡牌判断、提示推荐等核心算法。

## 主要文件路径

```
assets/game/scripts/calculator/
└── Calculator.ts    # 麻将算法核心 (98KB)
```

## 核心算法

### 牌型计算

**支持的牌型** (g_aryGainText):

| 牌型 | 倍数 | 说明 |
|------|------|------|
| 平胡 | 1 | 基础胡牌 |
| 七对 | 6 | 7对相同牌 |
| 碰碰胡 | 2 | 4组刻子+1对 |
| 清一色 | 6 | 单一花色 |
| 带幺九 | 32 | 含幺九牌 |
| 将对 | 3 | 特定对子 |
| 杠上开花 | 4 | 杠后自摸 |
| 天胡 | 48 | 庄家起手胡 |
| 地胡 | 24 | 闲家第一轮胡 |
| 龙七对 | 88 | 特殊七对 |

### 核心方法

```typescript
// 获取有效牌数
Calculator.getValidCardsCount(handCardIDs: number[]): number

// 计算换三张提示
Calculator.CalcPrompt3Cards_SameShape(
    handCardIDs: number[],
    handCardCnt: number,
    exchange3Cards: number[],
    exchange3CardsCnt: number
): void
```

## 牌值编码

**川麻有效牌值范围**: 1-9, 11-19, 21-29

| 范围 | 花色 |
|------|------|
| 1-9 | 万 |
| 11-19 | 条 |
| 21-29 | 筒 |

## 游戏类型常量

```typescript
ROOM_TYPE_XUELIU = 0x00000008           // 血流成河
ROOM_TYPE_EXCHANGE3CARDS = 0x00000010   // 换三张
ROOM_TYPE_XUELIUHONGZHONG = 0x00000020  // 血流红中
```

## 算法流程

```
手牌数据
    │
    ▼
Calculator.getValidCardsCount()
    │
    ▼
牌型匹配算法
    │
    ▼
返回胡牌类型及倍数
```

## 提示系统

### 胡牌提示

- `PromptHuManager.ts`: 胡牌提示管理
- 计算听牌列表
- 显示可胡牌型

### 出牌推荐

- `RecommendTipsManager.ts`: 推荐提示管理
- 分析最优出牌
- 显示推荐理由

## 注意事项

1. **性能优化**: 算法需频繁调用，注意缓存
2. **规则差异**: 不同玩法规则有差异
3. **边界情况**: 处理特殊牌型组合

## 业务术语

| 术语 | 含义 |
|------|------|
| lay | 牌值编码 |
| 根 | 额外加倍的牌型 |
| 癞子 | 可变牌（红中血流） |
