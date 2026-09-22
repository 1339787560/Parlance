# -*- coding: utf-8 -*-
"""make_deploy_pack 服务归属 / 打包范围测试。

回归锁定 2026-09-22 U8 的遗留缺口: `serviceServer-legacy` 从 `config.yaml` 摘除后,
legacy 目录不再匹配任何服务的 cwd 前缀 → 落 `shared` → `--only serviceServer-rust`
**静默漏发整个 legacy 目录** (模板/静态/数据层助手/CommonTools), 且 `deploy.bat` 的
旧双服务名调用直接 `未知服务名` 报错。修法 = `EXTRA_ASSET_PREFIXES` 把 legacy 目录
并回 `serviceServer-rust` 的资产域 (单服务名即覆盖全包)。
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import make_deploy_pack as m


# ── 归属 (EXTRA_ASSET_PREFIXES) ──────────────────────────────────────────────

def test_legacy_dir_files_are_owned_by_service_server_rust():
    owners = m._service_owners()
    for rel in (
        "serviceGroup/serviceServer-legacy/CustomRoute/templates/deposit.html",
        "serviceGroup/serviceServer-legacy/luaDataTool.py",
        "serviceGroup/serviceServer-legacy/CommonTools/xzmpDB/CpUserData.py",
        "serviceGroup/serviceServer-legacy/src/background/x.png",
    ):
        assert m._owner_of(rel, owners) == "serviceServer-rust", rel


def test_unowned_file_still_falls_back_to_shared():
    owners = m._service_owners()
    # 与 legacy 无关且不属于任何服务 cwd 前缀的文件仍是 shared (不误伤)
    assert m._owner_of("SDD/some/random.md", owners) == "shared"


def test_legacy_prefix_does_not_capture_sibling_dir():
    """`serviceServer/` 前缀不得吞掉 `serviceServer-legacy/` (两者互不前缀)。"""
    owners = m._service_owners()
    rust = owners["serviceServer-rust"]
    assert "serviceGroup/serviceServer/" in rust["prefixes"]
    assert "serviceGroup/serviceServer-legacy/" in rust["prefixes"]


# ── 打包范围 (collect_files) ────────────────────────────────────────────────

def test_only_service_server_rust_includes_legacy_assets():
    """核心回归: 单服务名必须带上 legacy 目录的运行资产。"""
    files, _ = m.collect_files(["serviceServer-rust"])
    for rel in (
        "serviceGroup/serviceServer-legacy/CustomRoute/templates/deposit.html",
        "serviceGroup/serviceServer-legacy/luaDataTool.py",
        "serviceGroup/serviceServer-legacy/cpDataTool.py",
        "serviceGroup/serviceServer-legacy/assetTool.py",
        "serviceGroup/serviceServer-legacy/script.json",
        "serviceGroup/serviceServer-legacy/CommonTools/xzmpDB/CpUserData.py",
        "serviceGroup/serviceServer-legacy/CommonTools/xzmpDB/LuaDataManager.py",
        "serviceGroup/serviceServer/spideOnlineLog.py",
    ):
        assert rel in files, rel


def test_per_machine_config_and_data_are_deliberately_not_packed():
    """按机配置 / 按机数据**刻意不入包** (各自有明确理由):

    - `config.json` (legacy 根) — `_is_config_name` 按 `config*` 前缀排除, 与 `config.yaml`
      同类: 服务清单/端口/路径**按机不同**, 随包覆盖会把目标机的服务定义换成打包机的。
    - `templates.db` — `.gitignore: *.db` 已忽略; Rust `TemplateStore::open` 缺库时自建,
      main.rs 注释写明「复用 legacy 库, **已有模板不丢**」⇒ 覆盖目标机库会丢现场模板。
    - `db_creds.enc` / `.enc.bak` — 按机凭据 (`~/.xzmp_db_key` 解密), INCLUDE_EXT 不含 .enc。

    三者都靠「首次部署初始化」(人工放置 / 运行期自建) 补齐。
    「初始化清单」= config.json + config.yaml + db_creds.enc (+ 可选 templates.db)。
    """
    files, skipped = m.collect_files(["serviceServer-rust"])
    for rel in (
        "serviceGroup/serviceServer-legacy/config.json",
        "serviceGroup/serviceServer-legacy/CustomRoute/templates.db",
        "serviceGroup/serviceServer-legacy/CommonTools/xzmpDB/db_creds.enc",
        "serviceGroup/serviceServer-legacy/CommonTools/xzmpDB/db_creds.enc.bak",
    ):
        assert rel not in files, rel
    # 被排除的配置要出现在 skipped 里 (可见, 不静默)
    assert "serviceGroup/serviceServer-legacy/config.json" in skipped


def test_oss_hosts_registry_is_packed():
    """`oss_hosts.yaml` 是 hostID→service 反查登记表 (非密), 随包同步目标机。"""
    files, _ = m.collect_files(["serviceServer-rust"])
    assert "serviceGroup/serviceServer-legacy/CommonTools/xzmpDB/oss_hosts.yaml" in files


def test_only_service_server_rust_excludes_retired_orphans():
    """孤儿 .py 清理 (2026-09-22) 后不得再入包。"""
    files, _ = m.collect_files(["serviceServer-rust"])
    for rel in (
        "serviceGroup/serviceServer-legacy/main.py",
        "serviceGroup/serviceServer-legacy/Service.py",
        "serviceGroup/serviceServer-legacy/JsonConfigParser.py",
        "serviceGroup/serviceServer-legacy/run_service.bat",
        "serviceGroup/serviceServer-legacy/CustomRoute/__init__.py",
        "serviceGroup/serviceServer-legacy/CustomRoute/ServiceRoute.py",
        "serviceGroup/serviceServer-legacy/CustomRoute/TemplateDB.py",
    ):
        assert rel not in files, rel


def test_legacy_dir_contributes_a_substantial_share():
    """legacy 目录是包内的实质组成部分, 不能被漏成一两个文件。"""
    files, _ = m.collect_files(["serviceServer-rust"])
    legacy = [f for f in files if f.startswith("serviceGroup/serviceServer-legacy/")]
    assert len(legacy) >= 30, f"legacy 入包仅 {len(legacy)} 个, 疑似归属回归"


def test_legacy_removed_service_name_now_errors_clearly():
    """旧双服务名调用应显式报错 (而非静默漏发) —— 文档/deploy.bat 已改单名。"""
    with pytest.raises(SystemExit):
        m.collect_files(["serviceServer-rust", "serviceServer-legacy"])


def test_full_pack_still_contains_legacy_assets():
    files, _ = m.collect_files(None)
    assert "serviceGroup/serviceServer-legacy/luaDataTool.py" in files


def test_deploy_bat_uses_single_service_name():
    """`deploy.bat` 是文档化的标准发布入口, 必须与打包范围一致 (单服务名)。

    双服务名在 U8 摘除 config 条目后直接 `未知服务名` —— 打包第一步即失败。
    """
    bat = (
        pathlib.Path(__file__).resolve().parents[1]
        / "serviceGroup" / "serviceServer" / "deploy.bat"
    ).read_text(encoding="ascii")
    assert "--only serviceServer-rust,serviceServer-legacy" not in bat
    assert "--only serviceServer-rust --push" in bat
