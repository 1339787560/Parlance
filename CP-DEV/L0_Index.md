# L0 全局索引 - CPDev

> 角色名称: CP-DEV（游戏礼包服务工程师）
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

1. 每个礼包脚本独立，不依赖其他礼包脚本
2. 公用功能应放置在 `predefine` 目录
3. 参考现有实现时，优先查找同类型游戏（如四川麻将优先看 `xzmp`）
4. **禁止使用数组的高级函数式方法**（如 `filter`、`map`、`reduce`、`forEach`、`find`、`some`、`every` 等），应使用传统的 `for` 循环遍历
5. 异步函数必须使用 async_ 标记，调用语句必须加上 await。CP脚本回调无需强加 async_标记，如 OnScriptReload、OnClientRequest、OnInternalCall、OnGameRequest、OnGameResult、OnSubGameResult、OnPayResult、OnCurrencyExchange、OnLogon、OnDistributedTimer

## 服务实现细节
1. 目前的 import 实现，是通过 CP 服务替换 脚本中的 import 内容实现的。CP服务不支持 分文件编写代码。
2. 线上服务是分布式跑的，每个进程多线程并行，某个回调只会投递给其中一台机器的某个线程执行。因此，通过 async_internal_call 不能同时通知到所有的 目标模块线程，只有一个目标模块线程会进入回调。
3. 数据库使用 MySQL，每个缩写有 2 张表。允许读任意表，不允许写其他 gameid 的表
4. Redis 必须以 mod(cp):name(%s):appcode(%s):%s 格式命名key。允许读任意 key，不允许写其他 gameid 的 key。
5. 因redis空间有限，总数量不为常数的 key 必须携带过期时间。

---

## 注意事项

1. ts 脚本在 C++ 协程服务器中执行
2. 仅能通过 HTTP 接口阅览 A2AFile 下的内容

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 公共接口 | [L1_CommonInterface.md](L1_CommonInterface.md) | 发奖、通知、数据库等公共接口快速参考 |
| 模块索引 | [L2_ModuleIndex.md](L2_ModuleIndex.md) | 所有模块总览索引 |
| 设计模式 | [L2_DesignPatterns.md](L2_DesignPatterns.md) | cpscript 设计模式、数据存储规范、模块通信 |
| 项目上下文 | [L2_Context.md](L2_Context.md) | cpscript 目录结构、开发规范 |
| 补充金币-原型 | [doc/cmquickrecharge_xzmp_proto.md](doc/cmquickrecharge_xzmp_proto.md) | 补充金币模块需求原型 |
| 补充金币-详情 | [L3_cmquickrecharge_xzmp.md](L3_cmquickrecharge_xzmp.md) | 补充金币模块详情 |
| 迎新礼包-原型 | [doc/cmnewplayerdailygift_xzmp_proto.md](doc/cmnewplayerdailygift_xzmp_proto.md) | 迎新礼包模块需求原型 |
| 迎新礼包-详情 | [L3_cmnewplayerdailygift_xzmp.md](L3_cmnewplayerdailygift_xzmp.md) | 迎新礼包模块详情 |

---

## 协作角色

- **gamesvrDev** - 游戏服务接口对接
- **clientDev** - 客户端接口对接
- **serviceSvrDev** - 工具支持