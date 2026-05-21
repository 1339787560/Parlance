# L1 - CommonTools 公共工具库

> 路径：`CommonTools/`

---

## 模块总览

```
CommonTools/
├── xzmpDB/           ← 游戏数据库工具
│   ├── DBConnector.py
│   ├── TQVIP.py      ← 荣耀特权 + 周卡/月卡管理器
│   └── tqvip_pb2.py  ← protobuf 消息定义
├── agent/            ← AI 工具
│   ├── anthropic_adapter.py
│   ├── chat_loop.py
│   └── speedTest.py  ← AI 模型 Benchmark
└── ragKnowledge/     ← RAG 知识库
    ├── __init__.py
    ├── config.py
    ├── document_processor.py
    ├── rag_engine.py       ← ChromaDB 引擎
    ├── scheduler.py        ← 飞书同步调度
    ├── evaluation.py
    └── rebuild_index.py
```

---

## xzmpDB — 游戏数据库

### DBConnector
MySQL 数据库连接器，封装连接池和查询执行。

### TQVIP — 特权/卡管理
**TQVIPManager**:
- `get_vip_data(user_id)` → `TQVip_PlayerData` protobuf 消息
- `set_vip_data(user_id, message)` → bool

**TQMonthCardManager**:
- `get_month_card_data(user_id)` → `TQMonthCard_Cache` protobuf 消息
- `set_month_card_data(user_id, cache)` → bool
- 同时管理周卡（`weekcard`）和月卡（`monthcard`）

**timeUtil**:
- `getdatenum(datetime)` → int（日期数字，如 20260521）
- `gettimenum(datetime)` → int（时间戳）
- `add_time_to_timenum(timenum, days=0)` → int（加天数）

### tqvip_pb2.py
由 protobuf 编译器生成的 Python 代码，定义 `TQVip_PlayerData` 和 `TQMonthCard_Cache` 消息结构。

---

## agent — AI 工具

### anthropic_adapter.py
封装 Anthropic SDK，提供 Claude API 调用接口，支持多模型。

### speedTest.py — AI Benchmark
- `run_benchmark(return_results=True)` → 执行压测，返回各模型延迟/吞吐量
- `save_benchmark(results, analysis)` → 保存测试结果
- `analyze_results(results)` → 分析结果
- `get_latest_benchmark()` → 获取最近一次测试
- `get_all_benchmarks()` → 获取所有历史测试
- 通过 ServiceRoute.py 的 API 暴露（`/api/benchmark/*`）

### chat_loop.py
AI 对话循环，用于交互式对话场景。

---

## ragKnowledge — RAG 知识库

### 技术架构
- **向量数据库**: ChromaDB（本地持久化，chroma_data/ 目录）
- **嵌入模型**: 支持多模型切换（sentence-transformers 等），通过 `config.py` 管理
- **检索策略**: 向量检索 + BM25 混合检索（rank_bm25）
- **中文分词**: jieba
- **文档源**: 飞书文档（通过 feishu2md 工具导出为 Markdown）

### 模块职责
| 文件 | 职责 |
|------|------|
| `rag_engine.py` | 核心引擎：索引构建、向量检索、SSE 流式问答、模型切换 |
| `document_processor.py` | 文档加载、分块、预处理 |
| `config.py` | 嵌入模型配置、连接设置 |
| `scheduler.py` | 异步飞书同步 + 索引重建调度 |
| `evaluation.py` | 检索质量评估 |
| `rebuild_index.py` | 索引重建工具 |

### 依赖
- chromadb>=0.4.0
- sentence-transformers>=2.2.0
- rank_bm25>=0.2.2
- jieba>=0.42.1
