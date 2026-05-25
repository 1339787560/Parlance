# L0 Index - LUA-Client-DEV-xzmp

> Lua 客户端工程师工作区索引

---

## 核心职责

维护线上旧版 Lua 客户端（Cocos2DX + Lua），为新版开发团队提供旧版本内容指导和支持。

---

## 技术栈

| 技术 | 说明 |
|------|------|
| Lua | 脚本语言 |
| Cocos2DX | 游戏引擎 |
| SVN | 版本控制 |

---

## 工作区索引

| 工作区 | 路径 | 说明 |
|--------|------|------|
| Lua 客户端 | D:\Codlib\douque\xzmx\ClientLua | 旧版客户端代码 |

---

## Test Execution

Legacy maintenance only — no new development or test execution required. Query historical functionality as needed.

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 角色描述 | [role_description.md](role_description.md) | 角色职责、技能范围、协作对象 |
| 工作流 | [WorkFlow/LUA-Client-DEV-xzmp_WorkFlow.md](../WorkFlow/LUA-Client-DEV-xzmp_WorkFlow.md) | BDD 描述 — 启动后行为、历史查询、维护模式限制 |

## L2 详细解析索引

| 模块 | 笔记路径 | 内容 |
|------|----------|------|
| 复活礼包 sectionid | [L2_BrokeRechargeNew_SectionId.md](L2_BrokeRechargeNew_SectionId.md) | sectionid 数据流、chunk 计算、宗师场无区分 |
| 新手教程 TqGameLesson | [L2_TqGameLesson.md](L2_TqGameLesson.md) | 客户端模拟对局机制、LessonData 14 阶段流程、状态机、触发链 |

---

## 协作角色

- **gamesvrDev** - 服务端协议对接、旧版协议兼容
- **clientDev** - 新旧版本功能对比、迁移指导
- **CPDev** - 礼包功能旧版实现参考
- **serviceSvrDev** - 工具支持
