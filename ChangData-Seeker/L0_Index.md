# L0 Index - ChangData-Seeker

> 数据查询角色 — 负责查询现有数据表结构与字段说明。仅查询 外网阶段的 数据。

---

## 核心职责

查询已接入的数据表，提供字段名称、类型、分区/主键标识、业务含义等信息，辅助其他角色做数据对接与分析。

---

## 技术栈

| 技术 | 说明 |
|------|------|
| Hive / MaxCompute | 数据存储与查询引擎 |
| SQL | 查询语言 |

---

## 查询约定

查询请求只输出 SQL/KQL，不执行。默认提供 SQL。

---

## 文档索引

| 层级 | 名称 | 笔记路径 | 说明 |
|------|------|----------|------|
| L1 | dwd_game_combatgains_si | [L1_dwd_game_combatgains_si.md](L1_dwd_game_combatgains_si.md) | 战绩明细表(准实时) — 对局结果、分数变动、设备信息等字段 |
| **L2** | **斗地主 APP 新增用户留存分析** | **[L2_landlord_retention_analysis.md](L2_landlord_retention_analysis.md)** | **三层留存分析框架（全局/分玩法/分客户端），覆盖所用表映射、SQL模式、核心结论与行动建议。源数据见 `../ExternDoc/landlord-analysis/`** |
