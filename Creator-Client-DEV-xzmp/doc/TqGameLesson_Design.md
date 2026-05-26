# TqGameLesson 新手教程设计文档

## 概述

为四川麻将 Creator 客户端实现新手教程对局功能。新玩家（nBout==0）进入"单机房"后触发客户端模拟对局，完成后通过 CP convert 模块领取奖励。

## 数据流

```
CP convert_xzmp push (migrationResult_convert_xzmp)
  → HallPlugin.handleMigrationResult() 新增 newPlayerLesson 分支
    → dispatch 到 HallPlugin 的 dataCenter
      → HallHelp.getTutorialState() 暴露 static getter
        → GameInfo / TqLessonCtrl 通过 getState("HallPlugin") 跨插件读取
          → isNeedLesson() 判断是否启动教程
```

## 文件改动

### Step 1: Hall 插件

| 文件 | 改动 |
|------|------|
| `plugins/hall/scripts/Define.ts` | HallDefine 新增 TutorialState 相关常量 |
| `plugins/hall/scripts/HallPlugin.ts` | handleMigrationResult 新增 newPlayerLesson 分支；onDataReducer 新增状态 |
| `plugins/hall/scripts/layers/HallHelp.ts` | 新增 getTutorialState / isTutorialCompleted static getter |

### Step 2: GameInfo

| 文件 | 改动 |
|------|------|
| `game/scripts/GameInfo.ts` | 新增 queryTutorialState / claimTutorialReward / getTutorialState 方法 |

### Step 3: 游戏内教程模块

| 文件 | 说明 |
|------|------|
| `game/scripts/lesson/TqLessonDef.ts` | 常量、枚举、消息类型定义 |
| `game/scripts/lesson/TqLessonData.ts` | 14 阶段教程数据（简化版） |
| `game/scripts/lesson/TqLessonCtrl.ts` | 教程控制器 |

### Step 4: Game.ts 接入

守卫点：游戏初始化后启动教程、牌局流程跳过网络、结算界面 roomSkip。

## 关键设计决策

1. 教程状态以 CP convert 模块 `newPlayerLesson.isCompleted` 为准
2. 默认值 `isCompleted = true` — 无状态时视为已对局
3. LessonData 简化为声明式数组，牌局细节与 Lua 版一致
4. 不依赖 GameSvr `lessonstatus` 协议，改用 CP 模块状态
