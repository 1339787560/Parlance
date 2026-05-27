# L0 全局索引 - 斗地主客户端

## 项目概述

**项目名称**: zgde (斗地主)
**技术栈**: Cocos Creator 3.8.1 + TypeScript
**项目类型**: 3D 斗地主游戏客户端

## 核心职责

负责 CocosCreator 3.8.1 下斗地主客户端的 ts 脚本编写。

### 主要工作内容

1. **游戏对局层开发** — 游戏场景逻辑、交互处理、动画效果实现
2. **礼包层开发** — 礼包界面、礼包功能逻辑
3. **配置管理** — 游戏资源配置、参数配置

## 工作常用目录

| 目录 | 路径 |
|------|------|
| 游戏对局层 | D:\Codlib\douque\zdga\cocos\trunk2.0\assets\game |
| 游戏礼包层 | D:\Codlib\douque\zdga\cocos\trunk2.0\assets\plugins |
| 游戏配置层 | D:\Codlib\douque\zdga\cocos\trunk2.0\assets\resources |
| 游戏模板层 | D:\CocosCreator2.0\Template |

## 技术栈清单

| 类别 | 技术 |
|------|------|
| 游戏引擎 | Cocos Creator 3.8.1 |
| 开发语言 | TypeScript |
| 项目类型 | 3D 游戏 |

## 核心架构

```
assets/
├── game/                         # 游戏核心代码
│   ├── scripts/                  # 脚本目录
│   │   ├── components/ (22个)    # UI组件 (GamePlugin.ts 主入口)
│   │   ├── manager/ (10个)       # 游戏管理器
│   │   ├── network/ (5个)        # 网络通信层
│   │   ├── calculator/           # 牌型算法
│   │   ├── layers/ (7个)         # 界面层
│   │   ├── event/                # 事件系统
│   │   ├── common/               # 通用工具
│   │   ├── smart/                # AI 逻辑
│   │   └── overrideaction/       # 重写 Action
│   ├── plugins/ (11个)           # 游戏内插件
│   └── ...                       # 动画、资源、配置等
├── plugins/ (16个)               # 功能模块插件
└── resources/                    # 资源文件
```

## 关键入口文件

| 文件 | 职责 |
|------|------|
| `assets/game/scripts/GameDef.ts` | 游戏定义 (牌数、座位、常量) |
| `assets/game/scripts/GameInfo.ts` | 游戏数据管理 |
| `assets/game/scripts/GamePlugin.ts` | 游戏主插件入口 |
| `assets/game/scripts/GameViewCtrl.ts` | 视图控制器 |
| `assets/game/scripts/GameInterface.ts` | 游戏接口定义 |

## 架构规约

1. **模块化设计**: 功能按插件划分，每个插件独立目录
2. **事件驱动**: 使用 eventCenter 进行模块间通信
3. **MVC 模式**: ViewCtrl 控制器模式管理视图
4. **网络层分离**: GameConnect 统一处理服务器通信

## Test Execution

Tests triggered via scene buttons in CocosCreator engine. Not fully automated — developer drives the flow. Module updates must expose a test entry point.

## 插件索引

### 大厅级插件 (`assets/plugins/`)

| 插件 | 目录 | 说明 |
|------|------|------|
| 破产引导 | ddzbankruptguide | 破产提示与引导流程 |
| 牌局抽奖 | ddzboutlottery | 牌局结束后抽奖 |
| 广播 | ddzbroadcast | 游戏内广播消息 |
| 输牌返还 | ddzloseback | 输牌后返还部分资源 |
| 比赛 | ddzmatch | 比赛模式功能 |
| 防沉迷 | ddzprotect | 未成年人防沉迷 |
| 签到 | ddzsignin | 每日签到奖励 |
| 任务 | ddztask | 任务系统 |
| 残局模式 | finalPhase | 残局模式，单机模式pve |
| 段位赛 | levelmatch | 段位匹配赛 |
| 登录 | login | 登录认证 |
| 救济 | relief | 救济金系统 |
| 举报 | report | 玩家举报 |
| 规则 | rules | 游戏规则说明 |
| 连胜 | serialwin | 连胜奖励 |
| 设置 | setting | 游戏设置 |

### 游戏内插件 (`assets/game/plugins/`)

| 插件 | 目录 | 说明 |
|------|------|------|
| 段位赛 | LevelMatch | 段位赛对局逻辑 |
| 广播 | ddzbroadcast | 对局内广播 |
| 比赛 | ddzmatch | 比赛对局逻辑 |
| 签到 | ddzsignin | 对局内签到 |
| 任务 | ddztask | 对局内任务 |
| 装饰 | decorate | 牌桌装饰 |
| 残局模式 | finalPhase | 联动游戏插件，本地 pve |
| 好友房 | frdroom | 好友开房 |
| 荣耀 | glory | 荣耀时刻 |
| 玩家信息 | playerinfo | 玩家信息展示 |
| 结算 | result | 牌局结算 |

## L1 模块笔记索引

| 模块 | 路径 | 职责 |
|------|------|------|
| 插件架构 | L1_PluginArchitecture.md | Plugin→Ctrl→Help→View 五层模式 |
| 游戏核心 | L1_GameCore.md | 游戏流程、牌局管理 |

## 协作角色

- **CPP-GameSVR-DEV-zgda** — 斗地主服务端接口对接

## 业务术语表 (Glossary)

| 术语 | 含义 |
|------|------|
| 斗地主 | 游戏类型 |
| 叫分 | 叫地主环节 |
| 抢地主 | 抢地主环节 |
| 底牌 | 三张底牌 |
| 春天 | 农民一张牌未出即结束 |
| 反春 | 地主只出一手牌即结束 |
| 加倍 | 加倍环节 |
| 明牌 | 亮出手牌 |
