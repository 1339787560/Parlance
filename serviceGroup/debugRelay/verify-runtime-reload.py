import asyncio
import json
import time
import urllib.request
import urllib.error
import websockets

URL = "ws://192.168.41.158:5003/ws/browser"
API = "http://192.168.41.158:5003/api/runtime/reload"

async def main():
    async with websockets.connect(URL) as ws:
        # Drain initial history quickly
        start = time.time()
        while time.time() - start < 1.0:
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.2)
            except asyncio.TimeoutError:
                break

        print("POST", API)
        req = urllib.request.Request(API, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            body = resp.read().decode("utf-8", errors="replace")
            print("HTTP", resp.status, body)
        except urllib.error.HTTPError as e:
            print("HTTP", e.code, e.read().decode("utf-8", errors="replace"))
            return

        seen = []
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            t = msg.get("type")
            if t in ("game_disconnected", "game_connected"):
                print("EVENT", t, msg.get("ts"))
                seen.append(t)
            elif t in ("console_log", "console_warn", "console_error", "console_info"):
                c = msg.get("content", "")
                if "runtime_reload" in c or "DebugPlugin" in c or "DebugClient" in c:
                    print("CONSOLE", t, c[:200])
            if "game_disconnected" in seen and "game_connected" in seen:
                break

        print("SEEN", seen)

asyncio.run(main())
