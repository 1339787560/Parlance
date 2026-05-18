# L0 全局索引 - CPDev

> 角色名称: CP-DEV-xzmp（游戏礼包服务工程师）
> 技能标签: TypeScript, CP服务, 协程服务器, 协议处理, 业务逻辑

> 游戏礼包服务工程师工作区全局索引

---

## 核心职责

负责编写 ts 脚本，脚本在 C++ 协程服务器中执行，应答客户端和服务端请求。

---

## 技术栈

| 技术 | 说明 |
|------|------|
| TypeScript | 主要开发语言 |
| C++ 协程 | 脚本执行环境 |
| 协议处理 | 客户端/服务端通信 |

---

## 工作区索引

| 工作区 | 路径 | 说明 |
|--------|------|------|
| 业务层 | D:\Codlib\other\ModCPSvr\cpscript\src\xzmp | 主要工作目录（四川麻将） |
| CP服务本体 | D:\Codlib\other\ModCPSvr | 服务代码（通常不查） |
| CP服务模板 | D:\LibraryVC14_p | 依赖模板 |

---

## 架构规约

1. **业务层优先**：主要在 cpscript/src/xzmp 下开发
2. **模板查阅**：需要时查阅 D:\LibraryVC14_p
3. **本体少动**：通常不修改 CP 服务本体代码

---

## 脚本开发规范

详见 [L1_DevStandards.md](L1_DevStandards.md)。

## 服务实现细节

1. 线上服务是分布式跑的，每个进程多线程并行，某个回调只会递交给其中一台机器的某个线程执行。因此，通过 async_internal_call 不能同时通知到所有的目标模块线程，只有一个目标模块线程会进入回调。
2. 数据库和 Redis 命名规约详见 [L1_DevStandards.md — 数据存储规范](L1_DevStandards.md#2-数据存储规范)。

---

## 注意事项

1. ts 脚本在 C++ 协程服务器中执行
2. 仅能通过 HTTP 接口阅览 A2AFile 下的内容
3. 测试入口: `TestTool.async_execAllTest()` (from `main()`)；运行: `NODE_TLS_REJECT_UNAUTHORIZED=0 node --loader ts-node/esm node_modules/ts-node/dist/bin.js src/xzmp/<module>.ts`
4. async 函数必须以 async_ 开头，否则无法通过 CP服务器的编译。async 函数的调用必须使用 await。
5. Redis 键命名格式：`mod(cp):name(${MODULE_NAME}):appcode(${APP_CODE}):uid(${uid}):${FUNC_INFO}`，锁 key 后缀 `:lock`。MySQL 表命名格式：`tblcpuserdata_${MODULE_NAME}_${GAME_CODE}`，字段名使用描述性名称（如 `CMMonthCardInfo`）。不得使用裸 redis/mysql 调用，必须封装为 RedisTool/MySqlTool 类。

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 公共接口 | [L1_CommonInterface.md](L1_CommonInterface.md) | 发奖、通知、数据库等公共接口快速参考 |
| 开发规范 | [L1_DevStandards.md](L1_DevStandards.md) | 编码规则、回调模式、数据存储规范、测试规范 |
| AI 工作规范 | [AI_Tool_BestPractices.md](../common/AI_Tool_BestPractices.md) | 渐进式加载 — 仅在讨论原型/开始实现时读取 |
| 工作流 | [WorkFlow/CP-DEV-xzmp_WorkFlow.md](../WorkFlow/CP-DEV-xzmp_WorkFlow.md) | BDD 描述 — 启动后行为、任务分发、测试执行流程 |
| 模块索引 | [L2_ModuleIndex.md](L2_ModuleIndex.md) | 所有模块总览索引 |
| 设计模式 | [L2_DesignPatterns.md](L2_DesignPatterns.md) | cpscript 设计模式、数据存储规范、模块通信 |
| 项目上下文 | [L2_Context.md](L2_Context.md) | cpscript 目录结构、开发规范 |
| 等级系统-详情 | [L3_leveldefine_xzmp.md](L3_leveldefine_xzmp.md) | 等级模块核心机制、降级/恢复、特权体系 |
| 补充金币-原型 | [doc/cmquickrecharge_xzmp_proto.md](doc/cmquickrecharge_xzmp_proto.md) | 补充金币模块需求原型 |
| 补充金币-详情 | [L3_cmquickrecharge_xzmp.md](L3_cmquickrecharge_xzmp.md) | 补充金币模块详情 |
| 迎新礼包-原型 | [doc/cmnewplayerdailygift_xzmp_proto.md](doc/cmnewplayerdailygift_xzmp_proto.md) | 迎新礼包模块需求原型 |
| 迎新礼包-详情 | [L3_cmnewplayerdailygift_xzmp.md](L3_cmnewplayerdailygift_xzmp.md) | 迎新礼包模块详情 |

---

## 协作角色

- **gamesvrDev** - 游戏服务接口对接
- **clientDev** - 客户端接口对接
- **serviceSvrDev** - 工具支持