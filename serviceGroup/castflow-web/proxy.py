#!/usr/bin/env python3
"""castflow-web — Castflow 远程访问统一入口（infoserver 托管子服务）。

定位：0.0.0.0:5130 -> 127.0.0.1:5120 的纯字节反向代理。
Castflow 自身已服务完整桌面 UI(/) + invoke 桥网关(/api/tauri/*) + 终端流(/terminal)
+ 事件总线(/events)，本代理只做网络暴露：平板/手机访问 http://<PC>:5130 即得
与桌面完全同源的界面；口令(Bearer/query token)由前端与 Castflow 之间透传，代理不解析。

设计要点：
- 零第三方依赖（stdlib socket + select），HTTP 与 WebSocket 升级后字节流通吃。
- /healthz 代理自答（含下游 TCP 探活），供人快速判断"门开了但店内没人"。
- 下游(Castflow)未运行 -> 502 明确提示，不静默。
- 不做 Host 重写：Castflow 各面不依赖 Host 头。

用法：python proxy.py [--port 5130] [--downstream 127.0.0.1:5120] [--bind 0.0.0.0]
"""
import argparse
import json
import select
import socket
import threading

LISTEN_HOST = "0.0.0.0"


def read_headers(client: socket.socket) -> bytes:
    """读到首个完整请求头（\r\n\r\n 为止）。返回已读全部字节。"""
    buf = b""
    while b"\r\n\r\n" not in buf:
        try:
            data = client.recv(4096)
        except OSError:
            return b""
        if not data:
            return b""
        buf += data
    return buf


def request_path(head_bytes: bytes) -> str:
    try:
        line = head_bytes.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split(" ")
        return parts[1] if len(parts) >= 2 else "/"
    except Exception:
        return "/"


def downstream_alive(downstream) -> bool:
    host, port = downstream
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        return True
    except OSError:
        return False


def handle(client: socket.socket, downstream):
    head = read_headers(client)
    if not head:
        client.close()
        return

    path = request_path(head)
    if path == "/healthz":
        up = downstream_alive(downstream)
        body = json.dumps(
            {
                "ok": True,
                "service": "castflow-web",
                "upstream": "{}:{}".format(*downstream),
                "upstream_alive": up,
            }
        ).encode()
        try:
            client.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
        except OSError:
            pass
        client.close()
        return

    try:
        up = socket.create_connection(downstream, timeout=5)
    except OSError:
        msg = b'{"ok":false,"error":"Castflow not running (downstream 5120 refused)"}'
        try:
            client.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(msg)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + msg
            )
        except OSError:
            pass
        client.close()
        return

    up.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        up.sendall(head)
    except OSError:
        client.close()
        up.close()
        return

    # 纯字节双向泵：select 等待任一侧可读/出错；无超时（长连接 WS 依赖静默保活）。
    socks = (client, up)
    try:
        while True:
            r, _, _ = select.select(socks, [], socks)
            if not r:
                break
            for s in r:
                other = up if s is client else client
                try:
                    data = s.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                try:
                    other.sendall(data)
                except OSError:
                    return
    finally:
        client.close()
        up.close()


def main():
    ap = argparse.ArgumentParser(description="castflow-web byte relay")
    ap.add_argument("--port", type=int, default=5130)
    ap.add_argument("--downstream", default="127.0.0.1:5120")
    ap.add_argument("--bind", default=LISTEN_HOST)
    args = ap.parse_args()
    host, _, dp = args.downstream.partition(":")
    downstream = (host, int(dp or 5120))

    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind((args.bind, args.port))
    ls.listen(64)
    print(f"[castflow-web] http://{args.bind}:{args.port} -> {downstream[0]}:{downstream[1]} (healthz=/healthz)", flush=True)
    while True:
        client, _ = ls.accept()
        threading.Thread(target=handle, args=(client, downstream), daemon=True).start()


if __name__ == "__main__":
    main()
