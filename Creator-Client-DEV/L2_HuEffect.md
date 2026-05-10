# L2 胡牌动效系统详解

## 概述

胡牌动效系统负责在玩家胡牌时播放特效动画，包括牌型特效、粒子效果、音效等。支持多种胡牌类型，按优先级选择最佳特效。

## 文件结构

```
assets/game/plugins/hueffect/
├── scripts/
│   ├── LayerHuEffect.ts       # 胡特效层 (主入口)
│   ├── HuEffectManager.ts     # 特效管理器
│   ├── HuTypeConfigs.ts       # 胡牌类型配置
│   ├── NodeWinParticle.ts     # 胜利粒子节点
│   └── NodeUintSilver.ts      # 银子节点
├── animations/                # 动画资源
├── particle/                  # 粒子资源
├── sounds/                    # 音效资源
└── images/                    # 图片资源
```

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                     胡牌动效系统架构                          │
├─────────────────────────────────────────────────────────────┤
│  LayerHuEffect (特效层)                                      │
│      │                                                      │
│      ├── showHuEffect() → 显示胡牌特效                       │
│      │                                                      │
│      ├── getBestHuEffectInfo() → 选择最佳特效                │
│      │                                                      │
│      ├── playCommonAnimationEffect() → 通用特效              │
│      │                                                      │
│      └── playSpecialAnimationEffect() → 特殊特效             │
│                                                             │
│  HuTypeConfigs (配置表)                                      │
│      │                                                      │
│      └── 定义所有胡牌类型的特效配置                          │
│                                                             │
│  动画类型                                                    │
│      │                                                      │
│      ├── 特殊动画 (spine) → 十三幺、天胡等                   │
│      │                                                      │
│      └── 通用动画 → 平胡、碰碰胡等                           │
└─────────────────────────────────────────────────────────────┘
```

## 胡牌类型配置

### IHuTypeConfig (配置接口)

```typescript
interface IHuTypeConfig {
    id: number;           // 编号
    effectType: number;   // 胡类型 [0,128]
    effectSubType: number; // 备用子类型
    name: string;         // 名称
    priority: number;     // 优先级 (越小越优先)
    timescale: number;    // 动画速度倍率
    resource: string;     // 资源路径
    animations: string;   // 动画名称
    imgagename?: string[]; // 图片序列
    gains: number;        // 番数
}
```

### 胡牌类型优先级表

| 优先级 | 牌型 | 番数 |
|--------|------|------|
| 0 | 天胡、地胡、海底捞月、妙手回春、杠上开花 | 8-88 |
| 1 | 十三幺、连清七对、九莲宝灯、绿一色、大三元、大四喜 | 88 |
| 2 | 四暗刻、小三元、小四喜、字一色 | 64 |
| 3 | 混幺九 | 32 |
| 4 | 清幺九、清一色、七星不靠、全小/中/大 | 24 |
| 5 | 三暗刻、清龙 | 16 |
| 6 | 七对、全不靠、大于五、小于五 | 12 |
| 7 | 抢杠胡、杠上炮、无番胡 | 6-8 |
| 8 | 碰碰胡、混一色、双暗杠、全求人、五门齐 | 6 |
| 9 | 胡绝张、不求人 | 4 |
| 10 | 断幺、平胡、门前清 | 2 |
| 11 | 单吊将、坎张、边张、缺一门、双暗刻 | 1-2 |
| 12 | 自摸、暗杠、明杠、赖子杠 | 1-8 |

## LayerHuEffect (特效层)

### 核心属性

| 属性 | 类型 | 用途 |
|------|------|------|
| `node_Effects` | Node | 特殊特效节点 |
| `node_CommonEffects` | Node[] | 通用特效节点数组 |
| `spCommon` | sp.Skeleton[] | 通用骨骼动画 |
| `node_hu` | Node[] | 胡动画节点 |
| `node_particleList` | Node[] | 粒子节点 |

### 核心方法

```typescript
// 显示胡牌特效
showHuEffect(data: huEffectDataUnit): boolean

// 获取最佳胡牌特效
getBestHuEffectInfo(huFlags: number[]): IHuTypeConfig

// 播放通用动画特效
playCommonAnimationEffect(chairIndex: number, config: IHuTypeConfig, aniName: string)

// 播放特殊动画特效
playSpecialAnimationEffect(chairIndex: number, config: IHuTypeConfig, aniName: string)

// 重置
reset()
```

## 数据结构

### huEffectDataUnit (胡牌数据)

```typescript
interface huEffectDataUnit {
    userId: number;       // 用户ID
    winChairNo: number;   // 胡牌座位
    fangChairNo: number;  // 放炮座位
    huCardId: number;     // 胡牌ID
    huZimo: number;       // 是否自摸 [0:否 1:是]
    huFlags: number[];    // 胡牌标记位 [0,1]
}
```

## 特效选择算法

```typescript
getBestHuEffectInfo(huFlags: number[]) {
    let maxPriority = -1;
    let bestConfig = null;
    
    for (let config of HuTypeConfigs) {
        let effectType = config.effectType;
        let flagMask = effectType >= 64 ? huFlags[1] : huFlags[0];
        
        // 检查是否命中该牌型
        if (!IS_BIT_SET(flagMask, 1 << effectType)) continue;
        
        // 选择优先级最高且资源有效的
        if (maxPriority == -1 || config.priority < maxPriority) {
            maxPriority = config.priority;
            bestConfig = config;
        }
    }
    
    return bestConfig;
}
```

## 动画播放流程

```
showHuEffect(data)
    │
    ▼
getBestHuEffectInfo(huFlags)  // 选择特效
    │
    ▼
判断资源类型
    │
    ├── "tongyongpaixing" → playCommonAnimationEffect()
    │   │
    │   └── 使用 spCommon[chairIndex] 播放
    │
    └── 特殊资源名 → playSpecialAnimationEffect()
        │
        └── 使用 node_Effects 播放
```

## 胡牌标记位 (HuFlags)

### dwHuFlags[0] (低位)

| 位 | 牌型 |
|----|------|
| 0 | 十三幺 |
| 1 | 连清七对 |
| 2 | 九莲宝灯 |
| 3 | 绿一色 |
| 4 | 清幺九 |
| 5 | 大三元 |
| 6 | 大四喜 |
| 7 | 四暗刻 |
| 8 | 天胡 |
| 9 | 地胡 |
| 10 | 小三元 |
| 11 | 小四喜 |
| 12 | 碰碰胡 |
| 13 | 清一色 |
| 14 | 混一色 |
| 15 | 字一色 |
| 16 | 混幺九 |
| 17 | 七星不靠 |
| 18 | 七对 |
| 19 | 全不靠 |
| 20 | 清龙 |

### dwHuFlags[1] (高位，枚举值-64)

| 位 | 牌型 |
|----|------|
| 64 | 全小 |
| 65 | 全中 |
| 66 | 全大 |
| 67 | 三暗刻 |
| 68 | 大于五 |
| 69 | 小于五 |
| 70 | 抢杠胡 |
| 71 | 海底捞月 |
| 72 | 妙手回春 |
| 73 | 杠上开花 |
| 74 | 双暗杠 |
| ... | ... |

## 资源路径

```typescript
const RESOURCE_FOLDER_PATH = "plugins/hueffect/animations/"
const RESOURCE_SOUND_PATH = "plugins/hueffect/sounds/"
const RESOURCE_IMAGE_PATH = "plugins/hueffect/images/"

// 远程资源 (iOS敏感词问题)
const REMOTE_RESOURCE_URL = "aHR0cHM6Ly9oNWdhbWUu..."  // Base64编码
```

## Known Issues / 避坑指南

### [2024-04] iOS敏感词打包问题

- **现象**: 部分特效名称被iOS拒绝
- **解决方案**: 资源URL使用Base64编码，运行时解码

### [2024-04] 多特效同时播放

- **现象**: 多个胡牌特效重叠
- **解决方案**: 使用 `_lastEffectTime` 控制播放间隔

### [2024-04] 动画资源未清理

- **现象**: 切换场景时动画残留
- **解决方案**: 在 `reset()` 中清理骨骼动画和缓存

### [2024-04] 通用特效复用

- **现象**: 通用特效节点数组需要正确索引
- **解决方案**: 使用 `chairIndex = huDrawIndex - 1` 计算索引
