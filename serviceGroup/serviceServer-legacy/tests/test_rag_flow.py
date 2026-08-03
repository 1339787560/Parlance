"""测试飞书文档拉取到分片索引的完整流程"""

import os
import sys
import subprocess
import time
import threading

# 获取项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

# 将项目根目录加入路径
sys.path.insert(0, PROJECT_DIR)

# 导入配置
from CommonTools.ragKnowledge.config import KNOWLEDGE_LIB_DIR
from CommonTools.ragKnowledge.scheduler import _build_feishu_export_command, RAGScheduler


def test_feishu_export():
    """测试飞书文档导出"""
    print("\n" + "=" * 60)
    print("测试 1: 飞书文档导出")
    print("=" * 60)

    print(f"导出目标目录: {KNOWLEDGE_LIB_DIR}")
    cmd_str = _build_feishu_export_command()
    print(f"执行命令: {cmd_str}")

    # 确保目标目录存在
    os.makedirs(KNOWLEDGE_LIB_DIR, exist_ok=True)

    try:
        # 在独立线程中执行，避免阻塞
        result_container = {'result': None, 'done': False}

        def run_export():
            try:
                cmd_str = _build_feishu_export_command()
                # 使用 Popen 实时打印输出到当前窗口
                # stdin=subprocess.PIPE 允许向进程发送输入
                process = subprocess.Popen(
                    cmd_str,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                # 实时读取并打印输出
                for line in process.stdout:
                    print(line.rstrip())

                # 导出完成后发送回车键跳过"按任意键退出"
                process.stdin.write('\n')
                process.stdin.flush()

                process.wait(timeout=600)
                result_container['result'] = process
            except Exception as e:
                result_container['result'] = e
            finally:
                result_container['done'] = True

        thread = threading.Thread(target=run_export, daemon=True)
        thread.start()

        # 等待完成
        print("等待飞书文档导出完成...")
        while not result_container['done']:
            time.sleep(2)
            print("  ...正在导出...")

        result = result_container['result']

        if isinstance(result, Exception):
            print(f"导出异常: {str(result)}")
            return False

        if result.returncode == 0:
            print("飞书文档导出成功")
            return True
        else:
            print(f"飞书文档导出失败，返回码: {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        print("飞书文档导出超时（超过10分钟）")
        return False
    except FileNotFoundError:
        print("找不到 feishu-doc-export.exe，请确保命令可用")
        return False
    except Exception as e:
        print(f"飞书文档导出异常: {str(e)}")
        return False


def test_document_files():
    """测试文档文件是否存在"""
    print("\n" + "=" * 60)
    print("测试 2: 检查导出的文档文件")
    print("=" * 60)

    if not os.path.exists(KNOWLEDGE_LIB_DIR):
        print(f"知识库目录不存在: {KNOWLEDGE_LIB_DIR}")
        return False

    # 查找 .md 文件
    md_files = []
    for root, dirs, files in os.walk(KNOWLEDGE_LIB_DIR):
        for f in files:
            if f.endswith('.md'):
                md_files.append(os.path.join(root, f))

    print(f"找到 {len(md_files)} 个 .md 文件")

    if md_files:
        # 显示前几个文件
        for f in md_files[:5]:
            size = os.path.getsize(f)
            print(f"  - {os.path.basename(f)} ({size} bytes)")

        if len(md_files) > 5:
            print(f"  ... 还有 {len(md_files) - 5} 个文件")
        return True
    else:
        print("未找到任何 .md 文件")
        return False


def test_rag_index():
    """测试 RAG 分片索引构建"""
    print("\n" + "=" * 60)
    print("测试 3: RAG 分片索引构建")
    print("=" * 60)

    # 设置 HF 镜像
    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

    try:
        from CommonTools.ragKnowledge.rag_engine import get_engine, RAGEngine

        print("初始化 RAG 引擎...")
        engine = get_engine()

        if not engine.embedding_model:
            print("Embedding 模型未加载，无法构建索引")
            return False

        print(f"Embedding 模型已加载: {engine.current_model_key}")
        print(f"当前索引状态: {engine.collection.count()} 个分片")

        # 获取状态
        status = engine.get_status()
        print(f"需要重建索引: {status['needs_reindex']}")

        # 构建索引
        print("开始构建索引...")
        result = engine.build_index()

        if result['success']:
            print(f"索引构建成功")
            print(f"  - 分片数量: {result['chunk_count']}")
            print(f"  - 耗时: {result['elapsed']:.2f} 秒")
            return True
        else:
            print(f"索引构建失败: {result['message']}")
            return False

    except Exception as e:
        print(f"RAG 索引测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_rag_query():
    """测试 RAG 问答功能"""
    print("\n" + "=" * 60)
    print("测试 4: RAG 问答功能")
    print("=" * 60)

    try:
        from CommonTools.ragKnowledge.rag_engine import get_engine

        engine = get_engine()

        # 测试问题
        test_questions = [
            "什么是机器人工具？",
            "如何配置服务？",
        ]

        for question in test_questions:
            print(f"\n测试问题: {question}")

            # 召回
            chunks = engine.retrieve(question)
            print(f"召回结果: {len(chunks)} 个分片")

            if chunks:
                for i, chunk in enumerate(chunks[:2]):
                    print(f"  [{i+1}] 来源: {chunk['source']}")
                    print(f"      内容摘要: {chunk['content'][:100]}...")

            return len(chunks) > 0

    except Exception as e:
        print(f"RAG 问答测试异常: {str(e)}")
        return False


def test_scheduler_integration():
    """测试调度器集成功能"""
    print("\n" + "=" * 60)
    print("测试 5: 调度器集成测试")
    print("=" * 60)

    try:
        scheduler = RAGScheduler()

        # 测试立即检查（force_check）
        print("测试 force_check 方法...")

        # 监控异步任务完成状态
        check_completed = {'done': False}

        def monitor_check():
            # 给调度器一些时间启动异步任务
            time.sleep(2)
            # 等待最多 5 分钟
            for i in range(150):
                time.sleep(2)
                print(f"  ...等待异步任务完成... ({i*2}s)")
                # 检查是否完成（通过检查索引状态）
                try:
                    from CommonTools.ragKnowledge.rag_engine import get_engine
                    engine = get_engine()
                    status = engine.get_status()
                    if status['chunk_count'] > 0:
                        check_completed['done'] = True
                        return
                except:
                    pass

        # 启动监控线程
        monitor_thread = threading.Thread(target=monitor_check, daemon=True)
        monitor_thread.start()

        # 触发检查
        scheduler.force_check()

        # 等待监控完成
        monitor_thread.join(timeout=300)

        if check_completed['done']:
            print("调度器集成测试成功")
            return True
        else:
            print("调度器异步任务未完成（可能是正常情况，如果飞书导出耗时较长）")
            return False

    except Exception as e:
        print(f"调度器集成测试异常: {str(e)}")
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("飞书文档拉取到分片索引完整流程测试")
    print("=" * 60)
    print(f"项目目录: {PROJECT_DIR}")
    print(f"知识库目录: {KNOWLEDGE_LIB_DIR}")
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # 测试 1: 飞书文档导出
    results['feishu_export'] = test_feishu_export()

    # 测试 2: 检查文档文件
    results['document_files'] = test_document_files()

    # 测试 3: RAG 索引构建
    if results['document_files']:
        results['rag_index'] = test_rag_index()
    else:
        results['rag_index'] = False
        print("跳过索引测试（无文档文件）")

    # 测试 4: RAG 问答
    if results['rag_index']:
        results['rag_query'] = test_rag_query()
    else:
        results['rag_query'] = False
        print("跳过问答测试（索引未构建）")

    # 测试 5: 调度器集成（可选）
    print("\n测试 5 为可选测试，跳过（需要长时间等待）")
    results['scheduler_integration'] = None

    # 输出总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)

    total = 0
    passed = 0

    for name, result in results.items():
        if result is None:
            status = "跳过"
        elif result:
            status = "通过"
            passed += 1
            total += 1
        else:
            status = "失败"
            total += 1

        print(f"  {name}: {status}")

    print(f"\n总计: {passed}/{total} 测试通过")

    return results


if __name__ == '__main__':
    run_all_tests()