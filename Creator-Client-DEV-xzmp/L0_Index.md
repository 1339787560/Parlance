# L0 全局索引 - 四川麻将客户端

## 项目概述

**项目名称**: xzmk (四川麻将)
**技术栈**: Cocos Creator 3.8.1 + TypeScript
**项目类型**: 3D 麻将游戏客户端

## 核心职责

负责 CocosCreator 3.8.1 下四川麻将客户端的 ts 脚本编写。

### 主要工作内容

1. **游戏对局层开发** — 游戏场景逻辑、交互处理、动画效果实现
2. **礼包层开发** — 礼包界面、礼包功能逻辑
3. **配置管理** — 游戏资源配置、参数配置

## 工作常用目录

| 目录 | 路径 |
|------|------|
| 游戏对局层 | D:\Codlib\douque\xzmx\ClientEngineGame\trunk\assets\game |
| 游戏礼包层 | D:\Codlib\douque\xzmx\ClientEngineGame\trunk\assets\plugins |
| 游戏配置层 | D:\Codlib\douque\xzmx\ClientEngineGame\trunk\assets\resources |
| 游戏模板层 | D:\CocosCreator2.0\Template |

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
| 工作流 | [WorkFlow/Creator-Client-DEV-xzmp_WorkFlow.md](../WorkFlow/Creator-Client-DEV-xzmp_WorkFlow.md) | BDD 描述 — 启动后行为、测试触发方式、UI 模块开发流程 |
| 核心游戏逻辑 | [L1_GameCore.md](L1_GameCore.md) | 游戏流程、牌局管理 |
| 网络通信 | [L1_Network.md](L1_Network.md) | 服务器连接、协议处理 |
| 麻将算法 | [L1_Calculator.md](L1_Calculator.md) | 牌型计算、胡牌判断 |
| UI 组件 | [L1_UIComponents.md](L1_UIComponents.md) | 界面组件、交互逻辑（含 3D 子系统 L2 索引） |
| 功能插件目录 | [L1_Plugins.md](L1_Plugins.md) | 40+ 插件目录索引、插槽与命名规范 |
| 插件架构 | [L1_PluginArchitecture.md](L1_PluginArchitecture.md) | Plugin→ViewCtrl→Help→View→Def 五层模式、API 速查 |
| 客户端模板 | [L1_ClientTemplate.md](L1_ClientTemplate.md) | 模板启动流程、插件工作流、数据中心、支付/行为树接口 |

## L2 详细解析索引

| 模块 | 笔记路径 | 内容 |
|------|----------|------|
| 背包系统 | [L2_BagSystem.md](L2_BagSystem.md) | 道具管理、装饰穿戴、数据同步 |
| 事件系统 | [L2_EventSystem.md](L2_EventSystem.md) | 事件定义、装饰器、事件流 |
| 3D 手牌系统 | [L2_3DHandCards.md](L2_3DHandCards.md) | 手牌架构、发牌流程、出牌交互 |
| 3D 牌桌系统 | [L2_3DGameDesk.md](L2_3DGameDesk.md) | 牌桌管理、平台适配、屏幕适配 |
| 胡牌动效系统 | [L2_HuEffect.md](L2_HuEffect.md) | 特效配置、优先级算法、动画播放 |
| 新手教程迁移 | [L2_TqGameLesson_Migration.md](L2_TqGameLesson_Migration.md) | Lua → Creator 新手教程迁移：触发链、25+ 守卫点、LessonData 模拟消息、结算跳转 |
| 新手教程实现 | [L2_TqGameLesson_Impl.md](L2_TqGameLesson_Impl.md) | Creator 端实际实现：状态管理、BTree Action 路由、Lesson 模块、runAction 调用模式 |

## 公共文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 匹配数据结构 | [shared/match_data_structures.md](../shared/match_data_structures.md) | 匹配请求/响应 JSON、状态枚举（来自 gamesvrDev） |

## 协作角色

- **CPP-GameSVR-DEV-xzmp** — 服务端接口对接
- **CP-DEV-xzmp** — 礼包服务接口

## 业务术语表 (Glossary)

| 术语 | 含义 |
|------|------|
| 川麻 | 四川麻将 |
| 血流 | 血流成河玩法 |
| 杠开 | 杠后补牌胡 |
| 点炮 | 别人出牌被胡 |
| 自摸 | 自己摸牌胡 |
| 换三张 | 开局换牌玩法 |
