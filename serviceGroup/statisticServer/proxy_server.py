#!/usr/bin/env python3
"""
Transparent proxy: http://127.0.0.1 -> DeepSeek API
With token usage & cache hit rate tracking.

Supports both formats:
- Anthropic: /v1/messages → https://api.deepseek.com/anthropic/v1/messages
- OpenAI:    /chat/completions or /v1/chat/completions → https://api.deepseek.com/v1/chat/completions
- OpenAI:    /v1/models → https://api.deepseek.com/v1/models

计费 (2026-07 起 DeepSeek V4):
- 模型映射: claude-haiku/sonnet → deepseek-v4-flash; claude-opus → deepseek-v4-pro;
  旧别名 deepseek-chat/deepseek-reasoner 已退役且均为 Flash 档, 重写为 deepseek-v4-flash。
- 峰谷计价: 北京时间每日 09:00-12:00 / 14:00-18:00 高峰翻倍, 按请求时刻落库 cost。
- 缓存命中段不重复计费: cost = miss*miss价 + hit*hit价 + out*out价。
"""

import os, re, json, time, uuid, sqlite3
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio

# ---- Config ----

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
# Base targets per format
ANTHROPIC_TARGET = os.environ.get("ANTHROPIC_TARGET", "https://api.deepseek.com/anthropic")
OPENAI_TARGET = os.environ.get("OPENAI_TARGET", "https://api.deepseek.com/v1")
# Legacy single target (kept for compat with existing TARGET env var)
TARGET = os.environ.get("TARGET", ANTHROPIC_TARGET)
PORT = int(os.environ.get("PORT", "8080"))
DB_PATH = Path(os.environ.get("DB_PATH", "stats.db"))

# ---- 定价（元 / 百万 tokens, DeepSeek V4 平时价, 2026-07 起）----
# V4 峰谷计价: 北京时间每日 09:00-12:00 / 14:00-18:00 高峰翻倍 (含起点不含终点)
# 旧别名 deepseek-chat / deepseek-reasoner 已于 2026-07-24 23:59 北京时间退役,
# 且两者均为 V4-Flash 档 (deepseek-reasoner = Flash 思考档, 绝非 Pro!)
PRICING = {
    "deepseek-v4-flash": {"miss": 1, "hit": 0.02, "out": 2, "label": "Flash"},
    "deepseek-v4-pro":   {"miss": 3, "hit": 0.025, "out": 6, "label": "Pro"},
}
PEAK_WINDOWS = [(9, 12), (14, 18)]  # 北京时间高峰时段 (含起始不含结束)
PEAK_MULTIPLIER = 2.0

MODEL_MAP = [
    (re.compile(r"claude-.*(haiku|sonnet).*"), "deepseek-v4-flash"),
    # 兼容新旧 opus 命名: claude-opus-4-8 / claude-3-opus-20240229 都必须走 Pro
    (re.compile(r"claude-.*opus.*"), "deepseek-v4-pro"),
    (re.compile(r"deepseek-chat"), "deepseek-v4-flash"),     # 旧别名 → Flash 非思考
    (re.compile(r"deepseek-reasoner"), "deepseek-v4-flash"), # 旧别名 → Flash 思考 (非 Pro!)
    (re.compile(r"deepseek-.*"), None),                      # deepseek-v4-* 已是最新名, 透传
]

def map_model(m: str) -> str:
    for pat, repl in MODEL_MAP:
        if pat.match(m):
            return repl or m
    return "deepseek-v4-flash"

def get_pricing(model: str) -> dict:
    """定价档位: deepseek-v4-pro → Pro; 其余(flash/chat/reasoner 旧别名) → Flash。"""
    m = (model or "").lower()
    if "deepseek-v4-pro" in m or m.endswith("pro"):
        return PRICING["deepseek-v4-pro"]
    return PRICING["deepseek-v4-flash"]

def is_peak_time(ts) -> bool:
    """北京时间峰谷判定。ts 为服务器本地 naive ISO(中国时区本地=UTC+8 即北京时间)。"""
    if not ts:
        return False
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return False
    h = ts.hour
    return any(lo <= h < hi for lo, hi in PEAK_WINDOWS)

def calc_cost(model: str, prompt: int, hit: int, out: int, ts=None) -> float:
    """费用(元) = 未命中×未命中价 + 命中×命中价 + 输出×输出价, 高峰时段翻倍。

    prompt 为总输入(含命中), miss = prompt - hit, 避免缓存命中段重复计费。
    峰谷按请求时刻 ts 判定, 故聚合查询必须用落库 cost 求和, 不能再按 token 汇总重算。
    """
    p = get_pricing(model)
    miss = max(int(prompt or 0) - int(hit or 0), 0)
    cost = (miss * p["miss"] + int(hit or 0) * p["hit"] + int(out or 0) * p["out"]) / 1_000_000
    if is_peak_time(ts):
        cost *= PEAK_MULTIPLIER
    return cost


# ---- 会话缓存策略建议 (重置 vs 继续) ----

SESSION_ADVICE_WINDOW = 10   # 近 N 次请求的统计窗口
ADVICE_HORIZON = 32          # "还要发起多少次请求"的评估视界 (继续成本 = N次 × 每请求命中成本)

def _avg(vals):
    return sum(vals) / len(vals) if vals else 0

def _split_tasks(rows, gap_param="", mode=""):
    """把按 ts ASC 的请求行切分为任务 (复用自适应间隔算法 Median+2×MAD)。

    行格式: (ts, session_id, model, prompt, completion, total, hit, latency, miss, cost)
    返回: 任务 dict 列表 (chronological, 最旧在前); 含 hit_cost/miss_cost 累计(按请求时刻算好)。
    """
    gap = 60
    if mode != "fixed" and len(rows) >= 3:
        ts_list = []
        for r in rows:
            try:
                ts_list.append(datetime.fromisoformat(r[0]))
            except Exception:
                continue
        gaps = [(ts_list[i + 1] - ts_list[i]).total_seconds() for i in range(len(ts_list) - 1)]
        sorted_gaps = sorted(gaps)
        n = len(sorted_gaps)
        median = sorted_gaps[n // 2]
        mad = sorted([abs(g - median) for g in gaps])[n // 2]
        gap = max(median + 2 * mad, 10)
        gap = min(gap, 600)
    else:
        gap = int(gap_param) if gap_param else 60  # default 60s
    tasks = []
    cur = None
    prev_ts = None
    prev_session = None
    for r in rows:
        try:
            this_ts = datetime.fromisoformat(r[0])
        except Exception:
            continue
        row_session = r[1] or ""
        # New task: different session, or gap > threshold within same session
        is_new = (cur is None or
                  row_session != prev_session or
                  (prev_ts is not None and row_session == prev_session and
                   (this_ts - prev_ts).total_seconds() > gap))
        if is_new:
            cur = {
                "task_id": len(tasks) + 1,
                "start": r[0], "end": r[0],
                "requests": 0, "session": row_session,
                "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0,
                "cache_hit_tokens": 0,
                "cache_miss_tokens": 0,
                "total_latency_ms": 0, "cost": 0.0, "peak_requests": 0,
            }
            tasks.append(cur)
        cur["end"] = r[0]
        cur["requests"] += 1
        if is_peak_time(r[0]):  # 高峰时段请求数 (北京时间 9-12 / 14-18)
            cur["peak_requests"] += 1
        cur["prompt_tokens"] += r[3] or 0
        cur["completion_tokens"] += r[4] or 0
        cur["total_tokens"] += r[5] or 0
        cur["cache_hit_tokens"] += r[6] or 0
        cur["cache_miss_tokens"] += r[8] or 0
        cur["total_latency_ms"] += r[7] or 0
        cur["cost"] += r[9] or 0  # 落库 cost 已含峰谷计价
        prev_ts = this_ts
        prev_session = row_session
    return tasks

def session_advice(session: str) -> dict:
    """给选中会话给出「重置 vs 继续同一会话」的 token 开销建议 (按请求粒度, 原价不计峰谷)。

    重置成本  = 当前会话未命中总额 × 未命中价 (重新预热所需的一次性开销)。
    继续成本  = ADVICE_HORIZON 次请求 × 近10次最大命中/请求 × 命中价
              (若还要发起这么多请求, 继续消耗命中缓存的 token 价格)。
    近10次最大命中: 每请求命中受缓存上下文大小约束, 实测无高值极端(max/median≤1.5),
             用最大值天然免疫 0/极低命中请求对平均值的干扰。
    判定     = 重置成本 < 继续成本 → 建议重置; 否则建议继续。
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT ts, model, cache_hit_tokens, cache_miss_tokens "
        "FROM requests WHERE session_id=? AND (prompt_tokens>0 OR completion_tokens>0) "
        "ORDER BY ts ASC", (session,)).fetchall()
    if not rows:
        return {"verdict": "insufficient", "reason": "该会话暂无有效请求", "requests": 0}
    n = len(rows)

    total_miss = sum(r[3] or 0 for r in rows)
    hits = [r[2] or 0 for r in rows]
    recent_hit = max(hits[-SESSION_ADVICE_WINDOW:])

    pricing = get_pricing(rows[-1][1])
    reset_cost = total_miss * pricing["miss"] / 1_000_000
    per_req_hit_cost = recent_hit * pricing["hit"] / 1_000_000
    continue_cost = ADVICE_HORIZON * per_req_hit_cost

    if total_miss <= 0:
        verdict, reason = "continue", "当前会话无未命中, 缓存由共享前缀维持, 重置无必要"
    elif recent_hit <= 0:
        verdict, reason = "continue", "近10次无缓存命中, 继续执行无命中开销, 重置无收益"
    elif reset_cost < continue_cost:
        verdict, reason = "reset", (f"未命中总额 ¥{reset_cost:.3f} < {ADVICE_HORIZON}次请求命中 ¥{continue_cost:.3f}, "
                                     "重启会话更省")
    else:
        verdict, reason = "continue", (f"未命中总额 ¥{reset_cost:.3f} ≥ {ADVICE_HORIZON}次请求命中 ¥{continue_cost:.3f}, "
                                       "继续更省")
    break_even = int(reset_cost / per_req_hit_cost) + 1 if per_req_hit_cost > 0 else None

    return {
        "session": session, "requests": n, "verdict": verdict, "reason": reason,
        "total_miss_tokens": int(total_miss),
        "reset_cost": round(reset_cost, 6),
        "recent_window": SESSION_ADVICE_WINDOW,
        "recent_hit_tokens": int(round(recent_hit)),
        "recent_hit_cost": round(per_req_hit_cost, 6),
        "horizon": ADVICE_HORIZON,
        "continue_cost": round(continue_cost, 6),
        "break_even_requests": break_even,
        "tier": pricing["label"], "hit_price": pricing["hit"], "miss_price": pricing["miss"],
    }


# ---- Format detection ----

def detect_format(path: str):
    """根据请求路径推断格式 + target base.

    Returns: (format, target_base)
        format: "openai" | "anthropic"
        target_base: 完整目标 URL 前缀
    """
    p = path.lower().lstrip("/")
    # OpenAI: chat/completions, v1/chat/completions, v1/models, v1/embeddings ...
    if p.startswith("chat/completions") or p.startswith("v1/chat/completions"):
        return "openai", OPENAI_TARGET
    if p.startswith("v1/models") or p.startswith("models"):
        return "openai", OPENAI_TARGET
    if p.startswith("v1/embeddings") or p.startswith("embeddings"):
        return "openai", OPENAI_TARGET
    # Anthropic: v1/messages
    if "messages" in p:
        return "anthropic", ANTHROPIC_TARGET
    # 默认 anthropic（保持向后兼容）
    return "anthropic", ANTHROPIC_TARGET


def normalize_path(path: str, fmt: str) -> str:
    """把请求路径规范化为目标 API 期望的路径

    OpenAI target = .../v1，路径不能再带 v1/ 前缀
    Anthropic target = .../anthropic，路径需要带 v1/ 前缀
    """
    p = path.lstrip("/")
    if fmt == "openai":
        if p.startswith("v1/"):
            p = p[3:]
        return p
    else:
        if not p.startswith("v1/"):
            p = "v1/" + p
        return p


def extract_usage(usage: dict, fmt: str) -> dict:
    """归一化 usage 字段，统一为内部 schema

    内部 schema 语义（与 OpenAI 一致）：
    - prompt_tokens: 本次请求所有输入 token（含命中和未命中）
    - cache_hit_tokens: 命中缓存的 token
    - cache_miss_tokens: 未命中缓存的 token（即新付费的 input）
    - prompt_tokens = cache_hit_tokens + cache_miss_tokens
    """
    if fmt == "openai":
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
            "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
        }
    else:
        # Anthropic: input_tokens 不含缓存部分（新付费的输入）
        # 总 prompt = input_tokens + cache_read + cache_creation
        new_input = usage.get("input_tokens", 0)
        cache_hit = usage.get("cache_read_input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        prompt = new_input + cache_hit + cache_creation
        completion = usage.get("output_tokens", 0)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cache_hit_tokens": cache_hit,
            "cache_miss_tokens": new_input + cache_creation,  # miss = 所有非命中部分
        }


def build_headers(fmt: str, request_headers) -> dict:
    """构造转发到上游的 headers - 优先透传客户端 key，回退到代理 key"""
    auth = request_headers.get("authorization") or f"Bearer {DEEPSEEK_API_KEY}"
    if fmt == "openai":
        return {
            "Authorization": auth,
            "Content-Type": "application/json",
        }
    else:
        return {
            "Authorization": auth,
            "Content-Type": "application/json",
            "anthropic-version": request_headers.get("anthropic-version", "2023-06-01"),
        }


# ---- DB ----

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                ts TEXT, session_id TEXT, model TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cache_hit_tokens INTEGER DEFAULT 0,
                cache_miss_tokens INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ok',
                format TEXT DEFAULT 'anthropic'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON requests(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON requests(session_id)")
        conn.commit()
        # Migrate old schema: add cache_miss_tokens if missing
        try:
            conn.execute("SELECT cache_miss_tokens FROM requests LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE requests ADD COLUMN cache_miss_tokens INTEGER DEFAULT 0")
            conn.commit()
        # Migrate: add format column if missing
        try:
            conn.execute("SELECT format FROM requests LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE requests ADD COLUMN format TEXT DEFAULT 'anthropic'")
            conn.commit()
        # Migrate: add cost column if missing (峰谷计价: 每次请求落库即按请求时刻算好费用)
        try:
            conn.execute("SELECT cost FROM requests LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE requests ADD COLUMN cost REAL DEFAULT 0")
            conn.commit()
        # Backfill: 旧行按修正后公式补算 cost (ts 视为北京时间; 修复缓存双重计费 + 接入峰谷)
        rows = conn.execute(
            "SELECT id, ts, model, prompt_tokens, cache_hit_tokens, completion_tokens "
            "FROM requests WHERE (cost IS NULL OR cost = 0) AND (prompt_tokens > 0 OR completion_tokens > 0)"
        ).fetchall()
        for rid, ts, model, prompt, hit, out in rows:
            c = calc_cost(model, prompt, hit, out, ts)
            if c:
                conn.execute("UPDATE requests SET cost=? WHERE id=?", (c, rid))
        conn.commit()
    except sqlite3.OperationalError:
        raise
    return conn

_db = None
def get_db():
    global _db
    if _db is None:
        _db = init_db()
    return _db

_sse_clients: set[asyncio.Queue] = set()

async def broadcast(event: str, data: dict = None):
    for queue in list(_sse_clients):
        await queue.put({"event": event, "data": data or {}})

async def record(d: dict):
    conn = get_db()
    # 峰谷计价按请求时刻 ts 判定, 落库时一次算好, 聚合只做 SUM(cost)
    cost = calc_cost(d.get("model", ""), d.get("prompt_tokens", 0),
                     d.get("cache_hit_tokens", 0), d.get("completion_tokens", 0),
                     d.get("ts"))
    conn.execute("""
        INSERT OR REPLACE INTO requests
        (id, ts, session_id, model, prompt_tokens, completion_tokens,
         total_tokens, cache_hit_tokens, cache_miss_tokens, latency_ms, status, format, cost)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        d["id"], d.get("ts"), d.get("session_id", ""), d.get("model", ""),
        d.get("prompt_tokens", 0), d.get("completion_tokens", 0),
        d.get("total_tokens", 0), d.get("cache_hit_tokens", 0),
        d.get("cache_miss_tokens", 0),
        d.get("latency_ms", 0), d.get("status", "ok"),
        d.get("format", "anthropic"), cost,
    ))
    conn.commit()
    await broadcast("new_data")

# ---- Proxy ----

app = FastAPI(title="DS Proxy")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(request: Request, path: str):
    # Local endpoints
    if path == "health":
        return {
            "status": "ok",
            "anthropic_target": ANTHROPIC_TARGET,
            "openai_target": OPENAI_TARGET,
        }
    if path == "api/events":
        queue: asyncio.Queue = asyncio.Queue()
        _sse_clients.add(queue)
        async def event_stream():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=30)
                        yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                _sse_clients.discard(queue)
        return StreamingResponse(event_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"})
    if path == "" or path == "/":
        idx = static_dir / "index.html"
        return FileResponse(str(idx), media_type="text/html") if idx.exists() else {"status": "proxy_ready"}
    if path.startswith("api/") and not path.startswith("api/events"):
        return await handle_api(request, path)

    if not DEEPSEEK_API_KEY:
        return JSONResponse(500, {"error": "DEEPSEEK_API_KEY not set"})

    # Detect format from path
    fmt, target_base = detect_format(path)

    # Read + rewrite request
    raw = await request.body()
    body = json.loads(raw) if raw else {}
    body["model"] = map_model(body.get("model", ""))
    # OpenAI 默认非 stream，Anthropic 默认 stream
    is_stream = body.get("stream", fmt == "anthropic")
    req_id = f"req_{uuid.uuid4().hex[:16]}"
    session_id = (request.headers.get("x-claude-code-session-id")
                  or request.headers.get("x-session-id", ""))
    model = body["model"]
    start_ts = time.time()

    ds_headers = build_headers(fmt, request.headers)
    target_path = normalize_path(path, fmt)
    target_url = f"{target_base.rstrip('/')}/{target_path}"

    # ---- Non-streaming ----
    if not is_stream:
        async with httpx.AsyncClient() as c:
            try:
                r = await c.post(target_url, json=body, headers=ds_headers, timeout=300)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPStatusError as e:
                try:
                    ct = e.response.json()
                except Exception:
                    ct = {"error": e.response.text[:500]}
                await record({
                    "id": req_id, "ts": datetime.now().isoformat(),
                    "session_id": session_id, "model": model,
                    "latency_ms": int((time.time() - start_ts) * 1000),
                    "status": f"http_{e.response.status_code}", "format": fmt,
                })
                return JSONResponse(content=ct, status_code=e.response.status_code)
            except (httpx.RequestError, ValueError) as e:
                # 网络层故障(ConnectError/ReadError/Timeout) 或 JSON 解析失败
                await record({
                    "id": req_id, "ts": datetime.now().isoformat(),
                    "session_id": session_id, "model": model,
                    "latency_ms": int((time.time() - start_ts) * 1000),
                    "status": f"upstream_{type(e).__name__}", "format": fmt,
                })
                return JSONResponse(
                    content={"error": f"upstream: {type(e).__name__}: {str(e)[:200]}"},
                    status_code=502,
                )

        elapsed = int((time.time() - start_ts) * 1000)
        usage = data.get("usage", {})
        u = extract_usage(usage, fmt)
        await record({
            "id": req_id, "ts": datetime.now().isoformat(), "session_id": session_id,
            "model": data.get("model", model),
            **u,
            "latency_ms": elapsed, "status": "ok", "format": fmt,
        })
        return JSONResponse(content=data)

    # ---- Streaming ----
    async def stream():
        usage_data = {}
        err = False

        async with httpx.AsyncClient() as c:
            try:
                async with c.stream("POST", target_url, json=body, headers=ds_headers, timeout=300) as r:
                    if r.status_code != 200:
                        err = True
                        yield await r.aread()
                        return

                    if fmt == "anthropic":
                        # Anthropic SSE 格式：event: + data:
                        evt = ""
                        async for line in r.aiter_lines():
                            if line.startswith("event: "):
                                evt = line[7:].strip()
                                yield line + "\n"
                            elif line.startswith("data: "):
                                if evt == "message_start":
                                    try:
                                        m = json.loads(line[6:]).get("message", {})
                                        usage_data.update(m.get("usage", {}))
                                    except Exception:
                                        pass
                                elif evt == "message_delta":
                                    try:
                                        usage_data.update(json.loads(line[6:]).get("usage", {}))
                                    except Exception:
                                        pass
                                yield line + "\n"
                            else:
                                yield line + "\n"
                    else:
                        # OpenAI SSE 格式：仅 data: 行，结束标记 [DONE]
                        # usage 在最后一个 data 块（stream_options.include_usage=true）
                        async for line in r.aiter_lines():
                            if line.startswith("data: "):
                                payload = line[6:].strip()
                                if payload and payload != "[DONE]":
                                    try:
                                        chunk = json.loads(payload)
                                        if isinstance(chunk.get("usage"), dict):
                                            usage_data.update(chunk["usage"])
                                    except Exception:
                                        pass
                                yield line + "\n"
                            else:
                                yield line + "\n"
            except Exception as e:
                err = True
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        if not err and usage_data:
            elapsed = int((time.time() - start_ts) * 1000)
            u = extract_usage(usage_data, fmt)
            await record({
                "id": req_id, "ts": datetime.now().isoformat(), "session_id": session_id,
                "model": model,
                **u,
                "latency_ms": elapsed, "status": "ok", "format": fmt,
            })
        elif not err:
            await record({"id": req_id, "ts": datetime.now().isoformat(), "session_id": session_id,
                     "model": model, "latency_ms": int((time.time()-start_ts)*1000),
                     "status": "ok", "format": fmt})

    return StreamingResponse(stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

# ---- Stats API ----

async def handle_api(request: Request, path: str):
    conn = get_db()
    where = ""
    params = []
    # 手动触发前端刷新（用于数据迁移、外部直接改 DB 等场景）
    if path == "api/refresh":
        await broadcast("new_data")
        return {"status": "ok", "broadcast": "new_data"}
    if path == "api/stats/detail":
        # Per-request breakdown (last 100)
        rows = conn.execute(
            "SELECT ts,session_id,model,prompt_tokens,completion_tokens,total_tokens,"
            "cache_hit_tokens,cache_miss_tokens,latency_ms FROM requests "
            "ORDER BY ts DESC LIMIT 100"
        ).fetchall()
        return [{
            "ts": r[0], "session": r[1], "model": r[2],
            "prompt": r[3], "completion": r[4], "total": r[5],
            "cache_hit": r[6], "cache_miss": r[7], "latency_ms": r[8],
        } for r in rows]

    # Daily aggregation
    if path == "api/stats/daily":
        rows = conn.execute("""
            SELECT date(ts) as day, model,
                   COUNT(*),
                   COALESCE(SUM(prompt_tokens),0),
                   COALESCE(SUM(completion_tokens),0),
                   COALESCE(SUM(total_tokens),0),
                   COALESCE(SUM(cache_hit_tokens),0),
                   COALESCE(SUM(latency_ms),0),
                   COALESCE(SUM(cache_miss_tokens),0),
                   COALESCE(SUM(cost),0)
            FROM requests GROUP BY day, model ORDER BY day DESC
        """).fetchall()
        days = {}
        for r in rows:
            day = r[0]
            if day not in days:
                days[day] = {
                    "date": day, "requests": 0,
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    "cache_hit_tokens": 0, "cache_miss_tokens": 0,
                    "total_latency_ms": 0, "cost": 0.0, "model_costs": {},
                }
            d = days[day]
            d["requests"] += r[2]
            d["prompt_tokens"] += r[3]
            d["completion_tokens"] += r[4]
            d["total_tokens"] += r[5]
            d["cache_hit_tokens"] += r[6]
            d["total_latency_ms"] += r[7]
            d["cache_miss_tokens"] += r[8]
            c = r[9]  # 落库 cost 已含峰谷计价, 直接求和
            d["cost"] += c
            d["model_costs"][r[1]] = round(c, 6)
        result = []
        for d in days.values():
            d["avg_latency_ms"] = round(d["total_latency_ms"] / d["requests"]) if d["requests"] > 0 else 0
            d["cost"] = round(d["cost"], 6)
            del d["total_latency_ms"]
            result.append(d)
        return result

    # Task grouping: same session + time proximity = same task
    if path == "api/stats/tasks":
        limit = int(request.query_params.get("limit", 50))
        session = request.query_params.get("session", "")
        gap_param = request.query_params.get("gap", "")
        mode = request.query_params.get("mode", "")
        where_task = ""
        params_task = []
        if session:
            where_task = " WHERE session_id=? "
            params_task = [session]
        rows = conn.execute(f"""
            SELECT ts,session_id,model,prompt_tokens,completion_tokens,total_tokens,
                   cache_hit_tokens,latency_ms,cache_miss_tokens,cost
            FROM requests{where_task} ORDER BY ts ASC
        """, params_task).fetchall()

        tasks = _split_tasks(rows, gap_param, mode)

        # Compute total wall time + round cost (cost 已按请求累计, 含峰谷计价)
        for t in tasks:
            try:
                s = datetime.fromisoformat(t["start"])
                e = datetime.fromisoformat(t["end"])
                t["wall_time_ms"] = int((e - s).total_seconds() * 1000)
            except Exception:
                t["wall_time_ms"] = t["total_latency_ms"]
            t["cost"] = round(t["cost"], 6)
            t["is_peak"] = t["peak_requests"] > 0  # 任务含高峰请求 → 前端标 ×2

        tasks.reverse()
        tasks = tasks[:limit]
        return tasks

    # 会话缓存策略建议 (重置 vs 继续)
    if path == "api/stats/session/advice":
        sid = request.query_params.get("session", "")
        if not sid:
            return {"verdict": "insufficient", "reason": "缺少 session 参数", "requests": 0}
        return session_advice(sid)

    session = request.query_params.get("session")
    if session:
        where = " WHERE session_id=?"
        params = [session]

    # Aggregate
    row = conn.execute(f"""
        SELECT COUNT(*),
               COALESCE(SUM(prompt_tokens),0),
               COALESCE(SUM(completion_tokens),0),
               COALESCE(SUM(total_tokens),0),
               COALESCE(SUM(cache_hit_tokens),0),
               COALESCE(AVG(latency_ms),0),
               COALESCE(SUM(latency_ms),0),
               COALESCE(SUM(cache_miss_tokens),0),
               COALESCE(SUM(cost),0)
        FROM requests{where}
    """, params).fetchone()

    if not row or row[0] == 0:
        return {"total_requests": 0, "sessions": []}

    total_hit = row[4]
    total_miss = row[7]
    total_cost = row[8]

    # Cost per model (落库 cost 已含峰谷计价, 直接按模型求和)
    cost_rows = conn.execute(f"""
        SELECT model, SUM(prompt_tokens), SUM(cache_hit_tokens), SUM(completion_tokens),
               SUM(cost)
        FROM requests{where} GROUP BY model
    """, params).fetchall()

    model_costs = {}
    for m, prompt, hit, out, c in cost_rows:
        model_costs[m] = round(c or 0, 6)

    # Sessions
    sessions = []
    if not session:
        sess_rows = conn.execute("""
            SELECT session_id, MIN(ts), MAX(ts), COUNT(*), COALESCE(SUM(total_tokens),0)
            FROM requests WHERE session_id != '' GROUP BY session_id ORDER BY MAX(ts) DESC LIMIT 50
        """).fetchall()
        # Cost per session (落库 cost 已含峰谷计价, 直接求和)
        sess_cost_rows = conn.execute("""
            SELECT session_id, model,
                   SUM(prompt_tokens), SUM(cache_hit_tokens), SUM(completion_tokens),
                   SUM(cost)
            FROM requests WHERE session_id != '' GROUP BY session_id, model
        """).fetchall()
        sess_costs = {}
        for sid, m, pt, ht, ct, c in sess_cost_rows:
            sess_costs[sid] = sess_costs.get(sid, 0.0) + (c or 0)
        sessions = [{"id": r[0], "first": r[1], "last": r[2],
                      "count": r[3], "tokens": r[4],
                      "cost": round(sess_costs.get(r[0], 0.0), 6)} for r in sess_rows]

    return {
        "total_requests": row[0],
        "total_prompt_tokens": row[1],
        "total_completion_tokens": row[2],
        "total_tokens": row[3],
        "total_cache_hit_tokens": total_hit,
        "total_cache_miss_tokens": total_miss,
        "avg_latency_ms": round(row[5], 0),
        "total_time_ms": row[6],
        "total_cost": round(total_cost, 6),
        "model_costs": model_costs,
        "sessions": sessions,
    }

# ---- CLI ----

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--db", help="SQLite DB path")
    args = parser.parse_args()

    if args.db:
        DB_PATH = Path(args.db)
    if args.port:
        PORT = args.port

    if not DEEPSEEK_API_KEY:
        print("ERROR: set DEEPSEEK_API_KEY env var")
    else:
        print(f"Proxy http://{args.host}:{PORT}")
        print(f"  Anthropic → {ANTHROPIC_TARGET}")
        print(f"  OpenAI    → {OPENAI_TARGET}")
        print(f"Claude:    ANTHROPIC_BASE_URL=http://127.0.0.1:{PORT}")
        print(f"OpenAI SDK: base_url=http://127.0.0.1:{PORT}/v1")
        get_db()  # init on startup
        uvicorn.run(app, host=args.host, port=PORT, log_level="info")
