"""重建 RAG 知识库索引脚本"""

import os
import sys
import shutil

# 获取项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# 将项目根目录加入路径
sys.path.insert(0, PROJECT_DIR)

# 导入配置
import CommonTools.ragKnowledge.config as config
CHROMA_DB_DIR = config.CHROMA_DB_DIR
INDEX_STATUS_FILE = config.INDEX_STATUS_FILE


def rebuild_index():
    """重建 RAG 索引"""
    print("=" * 50)
    print("RAG 知识库索引重建工具")
    print("=" * 50)

    # 1. 清除旧的 ChromaDB 数据
    if os.path.exists(CHROMA_DB_DIR):
        print(f"[1] 清除旧索引数据: {CHROMA_DB_DIR}")
        try:
            shutil.rmtree(CHROMA_DB_DIR)
            print("    ✓ 清除成功")
        except Exception as e:
            print(f"    ✗ 清除失败: {e}")
            print("    请先停止 main.py 服务，再运行此脚本")
            return False
    else:
        print("[1] 无旧索引数据，跳过清除")

    # 2. 清除索引状态文件
    if os.path.exists(INDEX_STATUS_FILE):
        print(f"[2] 清除状态文件: {INDEX_STATUS_FILE}")
        try:
            os.remove(INDEX_STATUS_FILE)
            print("    ✓ 清除成功")
        except Exception as e:
            print(f"    ✗ 清除失败: {e}")
    else:
        print("[2] 无状态文件，跳过清除")

    # 3. 初始化引擎并重建索引
    print("[3] 初始化 RAG 引擎...")
    try:
        os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
        from CommonTools.ragKnowledge.rag_engine import RAGEngine

        engine = RAGEngine()

        if not engine.embedding_model:
            print("    ✗ Embedding 模型未加载，无法重建索引")
            return False

        print("[4] 重建索引...")
        result = engine.build_index()

        if result['success']:
            print(f"    ✓ 索引重建成功")
            print(f"    - 分片数量: {result['chunk_count']}")
            print(f"    - 耗时: {result['elapsed']:.2f} 秒")
        else:
            print(f"    ✗ 索引重建失败: {result['message']}")
            return False

    except Exception as e:
        print(f"    ✗ 初始化失败: {e}")
        return False

    print("=" * 50)
    print("索引重建完成！可以启动 main.py 服务了")
    print("=" * 50)
    return True


if __name__ == '__main__':
    success = rebuild_index()
    if not success:
        sys.exit(1)