import argparse
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from chat_manager import ChatManager
from database import Database
from file_handler import FileHandler
from routes import router
from state import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("parlanceChat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    upload_dir = app.state.upload_dir
    db_path = app.state.db_path

    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    state.db = Database(db_path)
    state.fh = FileHandler(upload_dir, tmp_dir=os.environ.get("PARLANCE_TMP_DIR", ""))
    # config 仅传给 ChatManager 占位; parlanceChat 自包含, 无外部 config 依赖
    state.chat = ChatManager(state.db, {})

    logger.info("parlanceChat started — upload=%s db=%s", upload_dir, db_path)
    yield

    if state.chat:
        await state.chat.sse.shutdown()
    if state.db:
        state.db.close()
    logger.info("parlanceChat shut down")


def create_app(upload_dir: str, db_path: str) -> FastAPI:
    app = FastAPI(lifespan=lifespan, title="Parlance Chat")
    app.state.upload_dir = upload_dir
    app.state.db_path = db_path

    # ── CORS (允许跨端口子服务页面嵌入/调用 theme API) ──────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Static files (共享资产位于 infoServer 根 static/) ──────────────────────
    # parlanceChat 是 infoserver 门面 + 主题 provider; 样式/背景图/前端资产归
    # infoServer/static/, 由本服务 (:5001) mount 提供给所有托管子服务跨端口引用
    # (集成指南见 docs/theme-integration.md)。路径: main.py → parlanceChat →
    # serviceGroup → infoServer, 上溯 3 级。
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    state.static_dir = static_dir
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    style_dir = static_dir / "style"
    # 用 is_dir() 而非 exists(): Windows 无 core.symlinks 时 git 符号链接
    # (static/style -> ../style) 物化为 8B 文本文件, exists()=True 但非目录,
    # StaticFiles 会抛 "Directory does not exist" 崩溃。is_dir() 兜底跳过。
    # 若 static/style 非目录 (Windows 符号链接未物化), 回退宿主根 style/
    # (gitignored 本地主题资产: kokomi/firefly/furina/geniusclub/Hysilens/silverwolf)。
    if not style_dir.is_dir():
        style_dir = Path(__file__).resolve().parent.parent.parent / "style"
    if style_dir.is_dir():
        app.mount("/style", StaticFiles(directory=str(style_dir)), name="style")

    # ── Middleware ───────────────────────────────────────────────────────────────
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

    app.include_router(router)
    return app


def main():
    parser = argparse.ArgumentParser(description="Parlance chat sub-service")
    parser.add_argument("--port", type=int, default=5001, help="HTTP port (default 5001)")
    parser.add_argument("--host", default="0.0.0.0", help="bind host")
    parser.add_argument("--upload-dir", default="./uploads", help="upload directory")
    parser.add_argument("--db-path", default="./data/chat.db", help="sqlite db path")
    args = parser.parse_args()

    app = create_app(args.upload_dir, args.db_path)
    # NOTE: 端口清理由 host ServiceGroupManager 的 config `port` 字段托管
    # (ManagedService.start 自动 _free_port)。独立直跑时若端口占用, uvicorn 会报错。

    # HTTPS support: set these env vars to run parlance over TLS.
    # Devices without HTTP/2 automatically fall back to HTTP/1.1 over TLS;
    # for plain-HTTP fallback use a reverse proxy (see deploy/Caddyfile.example).
    ssl_certfile = os.environ.get("PARLANCE_SSL_CERTFILE") or None
    ssl_keyfile = os.environ.get("PARLANCE_SSL_KEYFILE") or None
    ssl_keyfile_password = os.environ.get("PARLANCE_SSL_KEYFILE_PASSWORD") or None

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
        limit_concurrency=64,
        limit_max_requests=None,
        timeout_graceful_shutdown=1,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
        ssl_keyfile_password=ssl_keyfile_password,
    )


if __name__ == "__main__":
    main()
