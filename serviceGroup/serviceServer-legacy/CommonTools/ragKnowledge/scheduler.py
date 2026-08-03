"""定时调度器：每天检查并更新索引"""

import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Callable

from .config import (
    SCHEDULE_HOUR,
    SCHEDULE_MINUTE,
    KNOWLEDGE_LIB_DIR,
    FEISHU_EXPORT_PATH,
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_SPACE_ID,
    FEISHU_EXPORT_TYPE,
)
from .rag_engine import get_engine


def _build_feishu_export_command() -> str:
    """构建飞书文档导出命令"""
    return (
        f'{FEISHU_EXPORT_PATH} '
        f'--appId={FEISHU_APP_ID} '
        f'--appSecret={FEISHU_APP_SECRET} '
        f'--saveType={FEISHU_EXPORT_TYPE} '
        f'--spaceId={FEISHU_SPACE_ID} '
        f'--exportPath={KNOWLEDGE_LIB_DIR}'
    )


# 同步状态
_sync_status = {
    'running': False,
    'stage': '',  # 'exporting', 'indexing', 'done', 'error'
    'message': '',
    'progress': 0,
    'result': None
}


def get_sync_status() -> dict:
    """获取同步状态"""
    return _sync_status.copy()


class RAGScheduler:
    """RAG 定时调度器"""

    def __init__(self):
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._last_check_time = 0
        self._lock = threading.Lock()

    def start(self):
        """启动调度器"""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._schedule_next_check()
        print(f"[RAG Scheduler] 调度器已启动，将在每天 {SCHEDULE_HOUR}:{SCHEDULE_MINUTE} 检查索引")

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        print("[RAG Scheduler] 调度器已停止")

    def _schedule_next_check(self):
        """安排下一次检查"""
        if not self._running:
            return

        # 先取消已有的 Timer，防止重复调度
        if self._timer:
            self._timer.cancel()
            self._timer = None

        # 计算到下一个检查时间的秒数
        now = datetime.now()
        next_check = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0)

        # 如果今天的检查时间已过，安排到明天
        if next_check <= now:
            next_check += timedelta(days=1)

        delay_seconds = (next_check - now).total_seconds()

        print(f"[RAG Scheduler] 下一次检查将在 {next_check.strftime('%Y-%m-%d %H:%M:%S')} ({int(delay_seconds)}秒后)")

        self._timer = threading.Timer(delay_seconds, self._do_check)
        self._timer.daemon = True
        self._timer.start()

    def _do_check(self):
        """执行检查并更新索引"""
        self._last_check_time = time.time()

        print("[RAG Scheduler] 开始检查知识库...")

        # 在新线程中执行导出和索引，避免阻塞调度器
        thread = threading.Thread(target=self._do_check_async, daemon=True)
        thread.start()

        # 立即安排下一次检查（不等待异步任务完成）
        self._schedule_next_check()

    def _do_check_async(self):
        """异步执行导出和索引检查（在独立线程中运行）"""
        try:
            # 1. 先执行飞书文档导出
            print("[RAG Scheduler] 正在导出飞书文档...")
            export_success = self._export_feishu_docs()

            if not export_success:
                print("[RAG Scheduler] 飞书文档导出失败，跳过本次索引")
                return

            # 2. 检查并更新索引
            engine = get_engine()
            status = engine.get_status()

            # 如果需要重建索引
            if status['needs_reindex']:
                print("[RAG Scheduler] 知识库有更新，正在重建索引...")
                result = engine.build_index()
                print(f"[RAG Scheduler] 索引结果: {result}")
            else:
                print("[RAG Scheduler] 知识库无变化，跳过索引")

        except Exception as e:
            print(f"[RAG Scheduler] 检查失败: {str(e)}")

    def _export_feishu_docs(self, output_callback: Optional[Callable[[str], None]] = None) -> bool:
        """执行飞书文档导出命令

        Args:
            output_callback: 可选的输出回调函数，用于实时传递输出内容

        Returns:
            bool: 导出是否成功
        """
        global _sync_status

        try:
            cmd_str = _build_feishu_export_command()
            print(f"[RAG Scheduler] 执行命令: {cmd_str}")

            # 使用 CREATE_NEW_CONSOLE 让程序在自己的控制台窗口运行
            # 这样可以避免 stdin 重定向导致的 ReadKey 问题
            CREATE_NEW_CONSOLE = 0x00000010

            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=CREATE_NEW_CONSOLE  # 新建控制台窗口
            )

            # 实时读取并打印输出
            for line in process.stdout:
                line = line.rstrip()
                print(line)
                if output_callback:
                    output_callback(line)
                # 更新同步状态
                if _sync_status['running']:
                    # 解析进度信息（如果有的话）
                    if '导出文档' in line or '处理' in line:
                        _sync_status['message'] = line

            # 等待进程完成（最多10分钟）
            process.wait(timeout=600)

            if process.returncode == 0:
                print("[RAG Scheduler] 飞书文档导出成功")
                return True
            else:
                print(f"[RAG Scheduler] 飞书文档导出失败，返回码: {process.returncode}")
                return False

        except subprocess.TimeoutExpired:
            print("[RAG Scheduler] 飞书文档导出超时（超过10分钟）")
            process.kill()
            return False
        except FileNotFoundError:
            print("[RAG Scheduler] 找不到 feishu-doc-export.exe，请确保命令可用")
            return False
        except Exception as e:
            print(f"[RAG Scheduler] 飞书文档导出异常: {str(e)}")
            return False

    def force_check(self):
        """立即执行检查"""
        print("[RAG Scheduler] 立即检查知识库...")
        self._do_check()


# 全局调度器实例
_scheduler: Optional[RAGScheduler] = None


def get_scheduler() -> RAGScheduler:
    """获取全局调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = RAGScheduler()
    return _scheduler


def start_scheduler():
    """启动调度器"""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """停止调度器"""
    scheduler = get_scheduler()
    scheduler.stop()


def start_async_sync() -> dict:
    """异步启动飞书同步和索引重建

    Returns:
        dict: {'success': bool, 'message': str} 立即返回，表示是否成功启动任务
    """
    global _sync_status

    # 检查是否已有任务在运行
    if _sync_status['running']:
        return {
            'success': False,
            'message': '已有同步任务在进行中，请稍后再试'
        }

    # 重置状态
    _sync_status = {
        'running': True,
        'stage': 'exporting',
        'message': '正在导出飞书文档...',
        'progress': 0,
        'result': None
    }

    # 启动异步任务
    thread = threading.Thread(target=_do_async_sync, daemon=True)
    thread.start()

    return {'success': True, 'message': '同步任务已启动'}


def _do_async_sync():
    """异步执行同步任务（在独立线程中运行）"""
    global _sync_status
    scheduler = get_scheduler()

    try:
        # 1. 执行飞书文档导出
        _sync_status['stage'] = 'exporting'
        _sync_status['message'] = '正在导出飞书文档...'
        print("[RAG Sync] 正在导出飞书文档...")

        export_success = scheduler._export_feishu_docs()

        if not export_success:
            _sync_status = {
                'running': False,
                'stage': 'error',
                'message': '飞书文档导出失败',
                'progress': 0,
                'result': {'success': False, 'message': '飞书文档导出失败'}
            }
            return

        # 2. 重建索引
        _sync_status['stage'] = 'indexing'
        _sync_status['message'] = '正在重建索引...'
        print("[RAG Sync] 正在重建索引...")

        engine = get_engine()
        result = engine.build_index()

        index_success = result.get('success', False)

        if index_success:
            _sync_status = {
                'running': False,
                'stage': 'done',
                'message': '同步完成',
                'progress': 100,
                'result': {
                    'success': True,
                    'message': '同步完成，索引已重建',
                    'doc_count': result.get('doc_count', 0),
                    'chunk_count': result.get('chunk_count', 0)
                }
            }
            print(f"[RAG Sync] 同步完成: 文档数={result.get('doc_count', 0)}, 分片数={result.get('chunk_count', 0)}")
        else:
            _sync_status = {
                'running': False,
                'stage': 'error',
                'message': '索引重建失败',
                'progress': 0,
                'result': {'success': False, 'message': '索引重建失败'}
            }

    except Exception as e:
        print(f"[RAG Sync] 同步失败: {str(e)}")
        _sync_status = {
            'running': False,
            'stage': 'error',
            'message': str(e),
            'progress': 0,
            'result': {'success': False, 'message': str(e)}
        }


def sync_feishu_and_rebuild():
    """同步飞书文档并重建索引（同步版本，已弃用，请使用 start_async_sync）

    Returns:
        dict: {'success': bool, 'message': str, 'export_success': bool, 'index_success': bool}
    """
    scheduler = get_scheduler()

    try:
        # 1. 先执行飞书文档导出
        print("[RAG Sync] 正在导出飞书文档...")
        export_success = scheduler._export_feishu_docs()

        if not export_success:
            return {
                'success': False,
                'message': '飞书文档导出失败',
                'export_success': False,
                'index_success': False
            }

        # 2. 重建索引
        print("[RAG Sync] 正在重建索引...")
        engine = get_engine()
        result = engine.build_index()

        index_success = result.get('success', False)

        return {
            'success': True,
            'message': '同步完成，索引已重建',
            'export_success': True,
            'index_success': index_success,
            'doc_count': result.get('doc_count', 0),
            'chunk_count': result.get('chunk_count', 0)
        }

    except Exception as e:
        print(f"[RAG Sync] 同步失败: {str(e)}")
        return {
            'success': False,
            'message': str(e),
            'export_success': False,
            'index_success': False
        }
