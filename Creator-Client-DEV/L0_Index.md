# L0 全局索引 - 四川麻将客户端

## 项目概述

**项目名称**: xzmk (四川麻将)
**技术栈**: Cocos Creator 3.8.1 + TypeScript
**项目类型**: 3D 麻将游戏客户端

## 技术栈清单

| 类别 | 技术 |
|------|------|
| 游戏引擎 | Cocos Creator 3.8.1 |
| 开发语言 | TypeScript |
| 项目类型 | 3D 游戏 |
| 物理系统 | Cocos Physics System |

## 核心架构

```
assets/
├── game/                    # 游戏核心代码
│   ├── scripts/             # 脚本目录
│   │   ├── components/      # UI组件 (Game.ts 主入口)
│   │   ├── manager/         # 游戏管理器
│   │   ├── network/         # 网络通信层
│   │   ├── calculator/      # 麻将算法计算器
│   │   ├── event/           # 事件系统
│   │   └── common/          # 通用工具
│   ├── common/              # 公共定义 (GameDef, GameInfo, GamePlugin)
│   ├── plugins/             # 游戏内插件
│   └── extensions/          # 扩展模块
├── plugins/                 # 功能模块 (40+个业务插件)
└── resources/               # 资源文件
```

## 关键入口文件

| 文件 | 职责 |
|------|------|
| `assets/game/Init.ts` | 物理系统初始化入口 |
| `assets/game/scripts/components/Game.ts` | 主游戏场景控制器 |
| `assets/game/common/GameInfo.ts` | 游戏数据管理 (240KB+) |
| `assets/game/scripts/network/GameConnect.ts` | 网络连接管理 (110KB+) |
| `assets/game/scripts/calculator/Calculator.ts` | 麻将算法核心 (98KB+) |

## 架构规约

1. **模块化设计**: 功能按插件划分，每个插件独立目录
2. **事件驱动**: 使用 `eventCenter` 进行模块间通信
3. **MVC 模式**: ViewCtrl 控制器模式管理视图
4. **网络层分离**: GameConnect 统一处理服务器通信

## Test Execution

Tests triggered via scene buttons in CocosCreator engine. Not fully automated — developer drives the flow. Module updates must expose a test entry point.

## L1 模块笔记索引

| 模块 | 笔记路径 | 职责 |
|------|----------|------|
| 角色描述 | [Creator-Client-DEV.md](Creator-Client-DEV.md) | 角色职责、工作范围、协作关系 |
| 核心游戏逻辑 | [L1_GameCore.md](L1_GameCore.md) | 游戏流程、牌局管理 |
| 网络通信 | [L1_Network.md](L1_Network.md) | 服务器连接、协议处理 |
| 麻将算法 | [L1_Calculator.md](L1_Calculator.md) | 牌型计算、胡牌判断 |
| UI 组件 | [L1_UIComponents.md](L1_UIComponents.md) | 界面组件、交互逻辑（含 3D 子系统 L2 索引） |
| 功能插件目录 | [L1_Plugins.md](L1_Plugins.md) | 40+ 插件目录索引、插槽与命名规范 |
| 插件架构 | [L1_PluginArchitecture.md](L1_PluginArchitecture.md) | Plugin→ViewCtrl→Help→View→Def 五层模式、API 速查 |

## L2 详细解析索引

| 模块 | 笔记路径 | 内容 |
|------|----------|------|
| 背包系统 | [L2_BagSystem.md](L2_BagSystem.md) | 道具管理、装饰穿戴、数据同步 |
| 事件系统 | [L2_EventSystem.md](L2_EventSystem.md) | 事件定义、装饰器、事件流 |
| 3D 手牌系统 | [L2_3DHandCards.md](L2_3DHandCards.md) | 手牌架构、发牌流程、出牌交互 |
| 3D 牌桌系统 | [L2_3DGameDesk.md](L2_3DGameDesk.md) | 牌桌管理、平台适配、屏幕适配 |
| 胡牌动效系统 | [L2_HuEffect.md](L2_HuEffect.md) | 特效配置、优先级算法、动画播放 |

## 公共文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 匹配数据结构 | [shared/match_data_structures.md](../shared/match_data_structures.md) | 匹配请求/响应 JSON、状态枚举（来自 gamesvrDev） |

## 业务术语表 (Glossary)

| 术语 | 含义 |
|------|------|
| 川麻 | 四川麻将 |
| 血流 | 血流成河玩法 |
| 杠开 | 杠后补牌胡 |
| 点炮 | 别人出牌被胡 |
| 自摸 | 自己摸牌胡 |
| 换三张 | 开局换牌玩法 |
