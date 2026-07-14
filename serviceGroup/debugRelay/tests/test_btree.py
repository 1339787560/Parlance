"""行为树日志解析器单元测试。
覆盖 _parse_btree_log（结构日志 tree 块）与 _parse_btree_exec（执行轨迹 version/status 块）。
运行: cd serviceGroup/debugRelay && python -m pytest tests/test_btree.py -v
"""
import os
import sys

# 使脚本可直接导入同目录 debug_relay
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from debug_relay import _parse_btree_log, _parse_btree_exec  # noqa: E402


def test_parse_btree_log_tree_blocks():
    content = (
        'tree loginhall\n'
        '{"version":"0.3.0","title":"loginhall","root":"r1","nodes":{"r1":{"name":"MemPriority","children":["a"]}}}\n'
        'tree loginpostprocess\n'
        '{"title":"loginpostprocess","root":"r2","nodes":{"r2":{"name":"ForEach"}}}\n'
    )
    trees = _parse_btree_log(content)
    assert len(trees) == 2
    assert trees[0]["name"] == "loginhall"
    assert trees[0]["tree"]["title"] == "loginhall"
    assert trees[0]["tree"]["nodes"]["r1"]["name"] == "MemPriority"
    assert trees[1]["name"] == "loginpostprocess"


def test_parse_btree_log_skips_garbage():
    content = "tree only\n{NOT_JSON}\ntree good\n{\"title\":\"good\"}\n"
    trees = _parse_btree_log(content)
    # 坏 JSON 块被跳过，好块保留
    assert len(trees) == 1
    assert trees[0]["name"] == "good"


def test_parse_btree_exec_version_and_status():
    # 模拟单树执行日志: version 头 + status 序列（state 3=RUNNING, 1=SUCCESS）
    content = (
        "version 2\n"
        'status 3df0d773-aaaa 3 {"test":1}  \n'
        "status 4e567833-bbbb 3 {\"x\":2} \n"
        "status 3df0d773-aaaa 1   \n"
    )
    versions = _parse_btree_exec(content)
    assert len(versions) == 1
    v = versions[0]
    assert v["version"] == 2
    assert len(v["events"]) == 3
    assert v["events"][0]["nodeId"] == "3df0d773-aaaa"
    assert v["events"][0]["state"] == 3
    assert v["events"][0]["inProps"] == '{"test":1}'
    assert v["events"][2]["state"] == 1
    assert v["events"][2]["inProps"] == ""   # SUCCESS 无 props


def test_parse_btree_exec_multiple_versions():
    content = (
        "version 1\n"
        "status n1 1\n"
        "version 2\n"
        "status n1 3\n"
        "status n1 1\n"
    )
    versions = _parse_btree_exec(content)
    assert len(versions) == 2
    assert versions[0]["version"] == 1 and len(versions[0]["events"]) == 1
    assert versions[1]["version"] == 2 and len(versions[1]["events"]) == 2


def test_parse_btree_exec_status_without_version():
    # 无 version 头时 status 仍归入默认 version 0 块
    content = "status n1 3 {\"a\":1}\nstatus n1 1\n"
    versions = _parse_btree_exec(content)
    assert len(versions) == 1
    assert versions[0]["version"] == 0
    assert len(versions[0]["events"]) == 2
