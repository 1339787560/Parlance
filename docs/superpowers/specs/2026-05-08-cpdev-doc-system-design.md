# CP-DEV 文档体系完善设计

## 背景

CP-DEV 目录现有文档存在两个问题：
1. CP-DEV.md（角色描述）与 L0_Index.md 内容大量重复
2. 模块文档不全，缺少公共接口参考和模块索引

## 方案

采用最小改动方案（方案 A）：不重组现有文档，只合并重复内容并新增缺失文档。

## 改动清单

### 1. 合并 CP-DEV.md 到 L0_Index.md

- 将 CP-DEV.md 中 L0_Index 未覆盖的内容合入 L0_Index：
  - 角色基本信息（名称、技能标签）
  - 注意事项（ts 脚本在 C++ 协程服务器中执行、仅通过 HTTP 接口阅览 A2AFile）
- 合并后删除 CP-DEV.md
- 更新 L0_Index.md 的文档索引表，去掉 CP-DEV.md 条目

### 2. 新建 L1_CommonInterface.md

公共接口快速参考手册，定位为"我要做 X，该调什么、怎么调"。

内容结构：
1. **发奖接口** — 发放金币/道具的标准流程、分批处理、上限检查
2. **通知客户端** — `notifyClient` 的调用方式、消息格式、PB 协议号
3. **通知其他模块** — `async_internal_call` 的调用方式、请求/响应格式
4. **配置读取** — `loadConfig` 的使用方式、全局缓存机制
5. **数据库操作** — MySQL 查询/写入的标准模板、Redis 读写模板、双写模式
6. **分布式锁** — `async_redis_lock_key` 的使用方式

来源：从 L2_DesignPatterns.md 已有的 CommonFuncs 和工具类示例中提取接口签名和调用范式，不重复内部实现细节。

### 3. 新建 L2_ModuleIndex.md

模块总览索引，每个模块一行概要。

内容结构：
1. **模块总览表** — 模块名 | 功能概要 | 脚本文件名 | L3 文档链接
2. **模块分类** — 按功能分组（等级系统、月卡/充值、装饰、新手引导等）

已有文档（cmquickrecharge_xzmp、cmnewplayerdailygift_xzmp）保持原路径不变，在总览表中链接到现有 doc/ 文件。

### 4. 将 impl 文档改写为 L3 模块详情文档

`doc/` 目录的定位：存放 `proto`（原型文档，用于溯源）和 `L3` 模块详情文档。

改写规则：
- 以现有 impl 文档为基础，参考 CP-DEV 工作目录下的实际代码进行重写
- 严格遵循 L3 模板格式，确保所有模块的文档格式高度一致
- 改写完成后删除原 impl 文档，仅保留 proto 用于溯源
- L3 文档命名：`doc/L3_{模块名}.md`

具体操作：
- `doc/cmquickrecharge_xzmp_impl.md` → 参考代码重写为 `doc/L3_cmquickrecharge_xzmp.md`，删除 impl
- `doc/cmnewplayerdailygift_xzmp_impl.md` → 参考代码重写为 `doc/L3_cmnewplayerdailygift_xzmp.md`，删除 impl

L3 模板结构：

```markdown
# {模块名} 模块详情

## 基本信息
| 属性 | 值 |
|------|-----|
| 模块名 | MODULE_NAME |
| 脚本文件 | xxx_xzmp.ts |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述
<!-- 一段话描述模块做什么 -->

## 主要函数

### 客户端请求处理
| 函数 | 说明 |
|------|------|
| OnClientRequest | ... |

### 内部模块调用
| 函数 | 说明 |
|------|------|
| OnInternalCall | ... |

### 其他回调
| 函数 | 说明 |
|------|------|
| OnScriptReload | ... |

## 数据结构
<!-- 关键 interf 定义 -->

## 依赖模块
<!-- 依赖的其他模块名 -->

## 消息号列表
| 常量名 | 值 | 方向 |
|--------|-----|------|
```

### 5. 更新 L0_Index.md 文档索引

在 L0_Index.md 的文档索引表中新增：
- L1_CommonInterface.md
- L2_ModuleIndex.md

## 不变的部分

- L2_DesignPatterns.md — 保持不变，仍包含设计模式的完整说明
- L2_Context.md — 保持不变，仍包含目录结构和开发规范
- doc/cmquickrecharge_xzmp_proto.md — 保留，用于溯源
- doc/cmnewplayerdailygift_xzmp_proto.md — 保留，用于溯源

## 文件变更汇总

| 操作 | 文件 |
|------|------|
| 修改 | CP-DEV/L0_Index.md（合入角色描述，更新索引） |
| 删除 | CP-DEV/CP-DEV.md |
| 新建 | CP-DEV/L1_CommonInterface.md |
| 新建 | CP-DEV/L2_ModuleIndex.md |
| 重写→新建 | CP-DEV/doc/L3_cmquickrecharge_xzmp.md（从 impl 重写） |
| 重写→新建 | CP-DEV/doc/L3_cmnewplayerdailygift_xzmp.md（从 impl 重写） |
| 删除 | CP-DEV/doc/cmquickrecharge_xzmp_impl.md |
| 删除 | CP-DEV/doc/cmnewplayerdailygift_xzmp_impl.md |
