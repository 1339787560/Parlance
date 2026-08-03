"""RAG 知识问答模块"""

import threading
import sys

from .rag_engine import get_engine, init_engine
from .scheduler import get_scheduler, start_scheduler, stop_scheduler
from .document_processor import get_document_list, get_library_mtime
from .config import (
    KNOWLEDGE_LIB_DIR,
    CHUNK_SIZE,
    RETRIEVE_TOP_K,
    RERANK_TOP_K
)


def init_rag():
    """初始化 RAG 模块（在独立线程中执行，不阻塞主服务）"""
    print("[RAG] 正在初始化 RAG 知识问答模块...")

    def _init_async():
        """异步初始化，输出同步到当前 CLI"""
        try:
            # 初始化引擎
            print("[RAG] 正在加载 Embedding 模型...")
            status = init_engine()
            print(f"[RAG] 引擎初始化完成: {status}")

            # 启动调度器
            print("[RAG] 启动调度器...")
            start_scheduler()

            print("[RAG] 模块初始化完成")
        except Exception as e:
            print(f"[RAG] 初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()

    # 在独立线程中执行初始化
    init_thread = threading.Thread(target=_init_async, daemon=True)
    init_thread.start()

    # 立即返回，不阻塞主服务
    return {'status': 'initializing', 'message': 'RAG 模块正在后台初始化'}


def shutdown_rag():
    """关闭 RAG 模块"""
    stop_scheduler()
    print("[RAG] 模块已关闭")


# 导出的主要接口
__all__ = [
    'get_engine',
    'init_engine',
    'get_scheduler',
    'start_scheduler',
    'stop_scheduler',
    'init_rag',
    'shutdown_rag',
    'get_document_list',
    'get_library_mtime',
    'KNOWLEDGE_LIB_DIR',
    'CHUNK_SIZE',
    'RETRIEVE_TOP_K',
    'RERANK_TOP_K'
]