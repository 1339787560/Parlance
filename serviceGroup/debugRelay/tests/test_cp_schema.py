# -*- coding: utf-8 -*-
"""cp_schema 单元测试: schema 完整性 + 归一化形状 + 白名单。

覆盖 Test 面板「全局 CP」的单一真相源: 13 模块 43 req, 模块名/req 名/参数样例/读写标记。
运行: cd serviceGroup/debugRelay && python -m pytest tests/test_cp_schema.py -v
"""
import os
import sys

# 使脚本可直接导入同目录 cp_schema
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cp_schema import CP_REQ_SCHEMA, cp_catalog, cp_namespaces, find_req, validate  # noqa: E402

EXPECTED_MODULES = 13
EXPECTED_REQS = 43


def test_schema_integrity():
    assert validate() == []
    assert len(CP_REQ_SCHEMA) == EXPECTED_MODULES
    assert sum(len(v) for v in CP_REQ_SCHEMA.values()) == EXPECTED_REQS


def test_cp_catalog_shape():
    """catalog 与 /api/debug-index 同构, 前端/agent 共用解析。"""
    cat = cp_catalog()
    assert cat["ok"] is True
    assert cat["scope"] == "cp"
    assert cat["count"] == EXPECTED_REQS
    assert cat["namespace_count"] == EXPECTED_MODULES
    assert cat["categories"] == list(CP_REQ_SCHEMA.keys())


def test_cp_items_normalize():
    ns = cp_namespaces()
    assert "cp.award" in ns

    # 无参只读 req
    item = ns["cp.award"]["queryAdVideoCfg"]
    assert item["category"] == "award"       # 子分类 = 模块名
    assert item["ro"] is True
    assert item["arity"] == 0
    assert item["params"] == {}
    assert item["desc"]

    # 命名参数: arity = 参数个数, params 为 dict (区别于 debug-index 的位置参数数组)
    relic = ns["cp.award"]["takeReliefReward_v2"]
    assert relic["arity"] == 3
    assert relic["ro"] is False
    assert isinstance(relic["params"], dict)

    deco = ns["cp.cmdecoration"]["queryUserListsHeadFrameInfo"]
    assert deco["arity"] == 1
    assert deco["params"] == {"userIDList": [1040720, 0, 0, 0]}
    assert deco["ro"] is True

    # 每个模块一个命名空间, 每个 req 都进索引且带正确模块分类
    for module, entries in CP_REQ_SCHEMA.items():
        nsname = f"cp.{module}"
        assert nsname in ns
        assert set(ns[nsname].keys()) == {e["req"] for e in entries}
        for e in entries:
            assert ns[nsname][e["req"]]["category"] == module


def test_find_req_whitelist():
    assert find_req("award", "queryAdVideoCfg") is not None
    assert find_req("award", "noSuchReq") is None
    assert find_req("noSuchModule", "queryAdVideoCfg") is None
    assert find_req(None, None) is None
    # 两端空白容忍
    assert find_req(" award ", " queryAdVideoCfg ") is not None
    # 红线: req 名大小写敏感, 错大小写不得命中
    assert find_req("luckyturntable", "queryrunturntable") is None
    assert find_req("luckyturntable", "queryRunTurntable") is not None


def test_write_reqs_are_flagged():
    """ro=False 的写操作必须在 desc 里显式标 [写] (会真改玩家数据)。"""
    flagged = 0
    for module, entries in CP_REQ_SCHEMA.items():
        for e in entries:
            if not e["ro"]:
                flagged += 1
                assert "[写]" in e["desc"], f'{module}.{e["req"]} 写操作未标 [写]'
    assert flagged == 20, "写操作数量变化需同步确认"
