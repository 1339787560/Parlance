# 让 Codex 白嫖 DeepSeek V4：一个 Responses API 翻译代理的优雅解法

> 2025 年 12 月，Codex 宣布废弃 `wire_api = "chat"`；2026 年 2 月，chat/completions 支持被彻底移除。第三方模型提供商（如 DeepSeek）只认 Chat Completions 格式——两边说不同的「语言」。本文给出一个 200 行代理的解决方案。

---

## 一、问题：两种方言，鸡同鸭讲

Codex 现在要求 `wire_api = "responses"`，所有请求以 **OpenAI Responses API** 格式发出：

```json
// Codex 发出的请求
POST /v1/responses
{
  "model": "deepseek-v4-flash",
  "input": "写一个快排",
  "instructions": "你是一个 Python 专家",
  "stream": true
}
```

但 DeepSeek 只支持 **Chat Completions** 格式：

```json
// DeepSeek 期望的请求
POST /v1/chat/completions
{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "system", "content": "你是一个 Python 专家"},
    {"role": "user", "content": "写一个快排"}
  ],
  "stream": true
}
```

响应也一样——Response API 用 `output` 数组，Chat Completions 用 `choices[0].message`；流式 SSE 事件名也完全不同。

**直接配不通。**

---

## 二、解法：中间架一层翻译代理

思路很简单——在本地起一个 HTTP 代理，做两件事：

```
Codex (Responses API)                   DeepSeek (Chat Completions)
       │                                         │
       │  POST /v1/responses                     │
       │  {"input": "hello", ...}                │
       │                                         │
       ▼                                         │
┌──────────────────────┐                         │
│   responses_proxy    │  POST /v1/chat/completions
│   格式翻译层          │  {"messages": [...], ...}
│   :8099              ├────────────────────────►│
│                      │                         │
│                      │◄────────────────────────┤
│                      │  {"choices": [{...}]}   │
│   {"output": [...]}  │                         │
└──────────────────────┘                         │
       │
       ▼
    Codex 收到标准 Responses API 响应
```

一个 Python 脚本，用 aiohttp 实现，不到 300 行，支持非流式和 SSE 流式。

---

## 三、动手：三步跑起来

### 前置条件

- Python 3.10+，已安装 `aiohttp`：`pip install aiohttp`
- DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com/api_keys)）

### 第一步：下载代理脚本

```bash
mkdir -p ~/.codex
# 将文末的 responses_proxy.py 保存到 ~/.codex/responses_proxy.py
```

### 第二步：配置 Codex

编辑 `~/.codex/config.toml`：

```toml
[model_providers.deepseek]
name = "DeepSeek"
base_url = "http://127.0.0.1:8099/v1"
wire_api = "responses"
api_key = "sk-your-deepseek-api-key"

[models.deepseek-v4-flash]
display_name = "DeepSeek V4 Flash"
model_provider = "deepseek"
model_id = "deepseek-v4-flash"
context_window = 1048576

[models.deepseek-v4-pro]
display_name = "DeepSeek V4 Pro"
model_provider = "deepseek"
model_id = "deepseek-v4-pro"
context_window = 1048576
```

重点解释：
- `base_url` 指向本地代理的 `/v1` 路径
- `wire_api = "responses"` 告诉 Codex 发 Responses API 格式——代理会翻译
- `context_window = 1048576` 即 1M token，DeepSeek V4 的完整上下文

### 第三步：启动代理

```bash
export DEEPSEEK_API_KEY="sk-your-key"
python3 ~/.codex/responses_proxy.py --port 8099 &

# 验证
curl http://127.0.0.1:8099/health
# → {"status": "ok", "target": "https://api.deepseek.com/v1/chat/completions"}
```

或者用启动脚本（推荐）：

```bash
# 保存为 ~/.codex/proxy.sh，见文末
bash ~/.codex/proxy.sh start
bash ~/.codex/proxy.sh status
```

搞定。打开 Codex，选择 DeepSeek V4 Flash 或 V4 Pro，开写。

---

## 四、调优：V4 的 thinking 模式怎么开

DeepSeek V4 是推理模型。默认情况下代理关闭了 thinking（`disabled`），直接输出结果——对编码代理来说这样最快，不用看模型「自言自语」。

如果需要深度推理（复杂算法、架构设计、调试难题），切换 thinking 模式：

```bash
# 快速模式（默认，推荐日常编码）
export DEEPSEEK_THINKING=disabled

# 深度推理
export DEEPSEEK_THINKING=enabled       # 平衡
export DEEPSEEK_THINKING=medium        # 中强度
export DEEPSEEK_THINKING=high          # 高强度
export DEEPSEEK_THINKING=max           # 极限推理
```

修改后重启代理即生效。这个设计参考了 [deepseek-tui](https://github.com/adrianlerer/deepseek-tui) 的 `Shift+Tab` 循环 `off → high → max` 的思路——日常编码用 fast，复杂任务切 deep。

实测数据：

| thinking 模式 | 输出方式 | 延迟 | Token 消耗 |
|:---|:---|:---|:---|
| `disabled` | 直接输出 content | 快 | 低 |
| `enabled` | content + reasoning | 中 | 中 |
| `high` / `max` | 纯 reasoning_content | 慢 | 高 |

---

## 五、代理做了什么翻译？

### 请求翻译

| Responses API | → | Chat Completions |
|:---|---|:---|
| `input: "hello"` | → | `messages: [{"role":"user","content":"hello"}]` |
| `input: [{type:"message",role:"user",content:"..."}]` | → | 直接映射 |
| `instructions: "你是专家"` | → | 前置 `{"role":"system","content":"你是专家"}` |
| `max_output_tokens` | → | `max_tokens` |
| `tools: [...]` | → | `tools: [...]`（透传） |
| `reasoning: {effort:"high"}` | → | `thinking: {type:"enabled", effort:"high"}` |

### 响应翻译（非流式）

| Chat Completions | → | Responses API |
|:---|---|:---|
| `choices[0].message.content` | → | `output[0].content[0].text` |
| `choices[0].message.tool_calls` | → | `output` 中的 `function_call` 项 |
| `usage.prompt_tokens` | → | `usage.input_tokens` |

### 响应翻译（流式 SSE）

| Chat Completions SSE | → | Responses API SSE |
|:---|---|:---|
| `data: {"choices":[{"delta":{"content":"Hi"}}]}` | → | `event: response.output_text.delta` + `data: {"delta":"Hi"}` |
| `data: [DONE]` | → | `event: response.completed` |

---

## 六、进阶：V4 模型的特殊之处

测 DeepSeek V4 的时候发现一个坑：开启 thinking 后，输出放在 `reasoning_content` 字段而不是 `content`，原版 `content` 是空的。

```json
// V4 Flash with thinking enabled 的实际响应
{
  "choices": [{
    "message": {
      "content": "",                                          // ← 空的
      "reasoning_content": "用户要求写一个快排，我需要..."       // ← 实际输出在这里
    }
  }]
}
```

代理已经处理了这个情况：`content` 为空时自动 fallback 到 `reasoning_content`，Codex 侧无感知。

---

## 七、附：完整源码

### responses_proxy.py

```python
#!/usr/bin/env python3
"""
Responses API → Chat Completions 翻译代理
============================================
让 Codex 通过 Responses API 格式使用任何 Chat Completions 兼容的模型。

用法:
    export DEEPSEEK_API_KEY="sk-xxx"
    export DEEPSEEK_THINKING=disabled   # 可选: disabled|enabled|low|medium|high|max
    python3 responses_proxy.py --port 8099

Codex 配置 (~/.codex/config.toml):
    [model_providers.deepseek]
    name = "DeepSeek"
    base_url = "http://127.0.0.1:8099/v1"
    wire_api = "responses"
    api_key = "sk-xxx"

    [models.deepseek-v4-flash]
    display_name = "DeepSeek V4 Flash"
    model_provider = "deepseek"
    model_id = "deepseek-v4-flash"
    context_window = 1048576
"""

import json
import os
import sys
import time
import uuid
import argparse
import logging
import asyncio
import traceback

from aiohttp import web, ClientSession, ClientTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("proxy")


# ─── 请求翻译 ────────────────────────────────────────────────────────────

def responses_to_chat(body: dict) -> dict:
    chat = {"model": body.get("model", "deepseek-v4-flash")}

    messages = []
    instructions = body.get("instructions", "")
    if instructions:
        messages.append({"role": "system", "content": instructions})

    raw_input = body.get("input", [])
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                t = item.get("type", "message")
                if t == "message":
                    role = item.get("role", "user")
                    content = item.get("content", "")
                    if isinstance(content, list):
                        texts = [p.get("text","") if isinstance(p,dict) else str(p)
                                 for p in content if not (isinstance(p,dict) and p.get("type","").startswith("input_image"))]
                        content = "\n".join(texts)
                    messages.append({"role": role, "content": content})
                elif t == "function_call":
                    messages.append({"role": "assistant", "content": None,
                        "tool_calls": [{"id": item.get("call_id",""), "type": "function",
                            "function": {"name": item.get("name",""), "arguments": item.get("arguments","")}}]})
                elif t == "function_call_output":
                    messages.append({"role": "tool", "tool_call_id": item.get("call_id",""),
                        "content": item.get("output","")})

    chat["messages"] = messages

    for k_in, k_out in [("temperature","temperature"), ("top_p","top_p"),
                         ("max_output_tokens","max_tokens"), ("stream","stream"),
                         ("stop","stop"), ("frequency_penalty","frequency_penalty"),
                         ("presence_penalty","presence_penalty")]:
        if k_in in body:
            chat[k_out] = body[k_in]

    tools = body.get("tools", [])
    if tools:
        chat["tools"] = [{"type": "function", "function": t} if isinstance(t, dict) else t for t in tools]
    if "tool_choice" in body:
        chat["tool_choice"] = body["tool_choice"]

    # thinking 参数
    reasoning = body.get("reasoning")
    thinking_env = os.environ.get("DEEPSEEK_THINKING", "disabled")
    if reasoning and isinstance(reasoning, dict):
        effort = reasoning.get("effort", "")
        chat["thinking"] = {"type": "enabled", "effort": effort} if effort else \
                          {"type": "enabled"} if reasoning.get("enabled", True) else \
                          {"type": "disabled"}
    elif thinking_env:
        chat["thinking"] = {"type": "disabled"} if thinking_env in ("disabled","off","0","false") else \
                          {"type": "enabled"} if thinking_env in ("enabled","on","1","true") else \
                          {"type": "enabled", "effort": thinking_env}

    return chat


# ─── 响应翻译 (非流式) ────────────────────────────────────────────────────

def chat_to_responses(chat_resp: dict, model: str) -> dict:
    resp_id = f"resp_{uuid.uuid4().hex[:24]}"
    output = []
    choices = chat_resp.get("choices", [])
    if choices:
        msg = choices[0].get("message", {})
        text = msg.get("content") or msg.get("reasoning_content", "")
        if text:
            output.append({"id": f"msg_{uuid.uuid4().hex[:24]}", "type": "message",
                "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}]})
        for tc in msg.get("tool_calls") or []:
            output.append({"id": f"fc_{uuid.uuid4().hex[:24]}", "type": "function_call",
                "status": "completed", "call_id": tc.get("id",""),
                "name": tc.get("function",{}).get("name",""),
                "arguments": tc.get("function",{}).get("arguments","")})

    usage = chat_resp.get("usage", {})
    resp_usage = {"input_tokens": usage.get("prompt_tokens", 0),
                  "output_tokens": usage.get("completion_tokens", 0),
                  "total_tokens": usage.get("total_tokens", 0)}
    details = usage.get("completion_tokens_details", {})
    if "reasoning_tokens" in details:
        resp_usage["output_tokens_details"] = {"reasoning_tokens": details["reasoning_tokens"]}

    return {"id": resp_id, "object": "response", "created_at": int(time.time()),
            "status": "completed", "model": model, "output": output, "usage": resp_usage}


# ─── 流式 SSE 翻译 ──────────────────────────────────────────────────────

async def translate_stream(source, write, model: str):
    rid, mid = f"resp_{uuid.uuid4().hex[:24]}", f"msg_{uuid.uuid4().hex[:24]}"
    ts = int(time.time())
    empty_resp = {"id": rid, "object": "response", "created_at": ts, "status": "in_progress", "model": model, "output": []}

    await write(f"event: response.created\ndata: {json.dumps({'type':'response.created','response':empty_resp})}\n\n")
    await write(f"event: response.in_progress\ndata: {json.dumps({'type':'response.in_progress','response':empty_resp})}\n\n")

    full_text, final_usage, content_started = "", None, False
    buf = ""
    async for chunk, _ in source:
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line or line.startswith(":") or line == "data: [DONE]":
                if line == "data: [DONE]": buf = ""; break
                continue
            if not line.startswith("data: "): continue
            try: data = json.loads(line[6:])
            except: continue
            choices = data.get("choices", [])
            if not choices: continue
            delta = choices[0].get("delta", {})
            for key in ("reasoning_content", "content"):
                d = delta.get(key, "")
                if not d: continue
                full_text += d
                if not content_started:
                    content_started = True
                    await write(f"event: response.content_part.added\ndata: {json.dumps({'type':'response.content_part.added','item_id':mid,'output_index':0,'content_index':0,'part':{'type':'output_text','text':'','annotations':[]}})}\n\n")
                await write(f"event: response.output_text.delta\ndata: {json.dumps({'type':'response.output_text.delta','item_id':mid,'output_index':0,'content_index':0,'delta':d})}\n\n")
            if "usage" in data:
                final_usage = data["usage"]

    msg_out = {"id": mid, "type": "message", "status": "completed", "role": "assistant",
               "content": [{"type": "output_text", "text": full_text, "annotations": []}]}
    await write(f"event: response.output_item.done\ndata: {json.dumps({'type':'response.output_item.done','item':msg_out})}\n\n")
    if full_text:
        await write(f"event: response.content_part.done\ndata: {json.dumps({'type':'response.content_part.done','item_id':mid,'output_index':0,'content_index':0,'part':{'type':'output_text','text':full_text,'annotations':[]}})}\n\n")

    resp_usage = {}
    if final_usage:
        resp_usage = {"input_tokens": final_usage.get("prompt_tokens", 0),
                      "output_tokens": final_usage.get("completion_tokens", 0),
                      "total_tokens": final_usage.get("total_tokens", 0)}
    await write(f"event: response.completed\ndata: {json.dumps({'type':'response.completed','response':{'id':rid,'object':'response','created_at':ts,'status':'completed','model':model,'output':[msg_out],'usage':resp_usage}})}\n\n")


# ─── HTTP 处理 ───────────────────────────────────────────────────────────

async def handle_responses(request: web.Request):
    try: body = await request.json()
    except: return web.json_response({"error": "Invalid JSON"}, status=400)

    target = request.app["target_url"]
    api_key = request.app["api_key"]
    is_stream = body.get("stream", False)
    model = body.get("model", "deepseek-v4-flash")

    try: chat_body = responses_to_chat(body)
    except Exception as e: return web.json_response({"error": str(e)}, status=400)

    if is_stream:
        chat_body.setdefault("stream_options", {})["include_usage"] = True

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    timeout = ClientTimeout(total=300)

    try:
        async with ClientSession(timeout=timeout) as sess:
            async with sess.post(target, json=chat_body, headers=headers) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    return web.Response(status=resp.status, text=err, content_type="application/json")
                if is_stream:
                    ws = web.StreamResponse()
                    ws.headers["Content-Type"] = "text/event-stream"
                    ws.headers["Cache-Control"] = "no-cache"
                    await ws.prepare(request)
                    async def w(data): await ws.write(data.encode())
                    await translate_stream(resp.content.iter_chunks(), w, model)
                    await ws.write_eof()
                    return ws
                else:
                    return web.json_response(chat_to_responses(await resp.json(), model))
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)


async def health(request): return web.json_response({"status": "ok", "target": request.app["target_url"]})


def main():
    p = argparse.ArgumentParser(description="Responses → Chat Completions 翻译代理")
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--target", type=str, default="https://api.deepseek.com/v1/chat/completions")
    p.add_argument("--api-key", type=str, default=None)
    p.add_argument("--host", type=str, default="127.0.0.1")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    app = web.Application()
    app["target_url"], app["api_key"] = args.target, api_key
    app.router.add_post("/v1/responses", handle_responses)
    app.router.add_get("/health", health)

    print(f"Responses API 翻译代理 | {args.host}:{args.port} → {args.target}")
    print(f"Thinking: {os.environ.get('DEEPSEEK_THINKING','disabled')}")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

### proxy.sh（启动管理脚本）

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY_SCRIPT="$SCRIPT_DIR/responses_proxy.py"
PID_FILE="$SCRIPT_DIR/proxy.pid"
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY}"
export DEEPSEEK_THINKING="${DEEPSEEK_THINKING:-disabled}"

case "${1:-start}" in
    start)
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "代理已在运行 (PID: $(cat $PID_FILE))"; exit 0
        fi
        nohup python3 "$PROXY_SCRIPT" --port 8099 >> "$SCRIPT_DIR/proxy.log" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        kill -0 $(cat "$PID_FILE") 2>/dev/null && echo "✅ 已启动 (PID: $(cat $PID_FILE))" || echo "❌ 启动失败"
        ;;
    stop)
        [ -f "$PID_FILE" ] && kill $(cat "$PID_FILE") 2>/dev/null && rm -f "$PID_FILE" && echo "✅ 已停止"
        ;;
    status)
        [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null && curl -s http://127.0.0.1:8099/health | python3 -m json.tool || echo "❌ 未运行"
        ;;
    *) echo "用法: $0 {start|stop|status}" ;;
esac
```

---

## 八、写在最后

这个代理本质上是一个**协议适配器**。它的优雅之处在于：

1. **零侵入**——Codex 不需要任何修改，只改 `config.toml` 里的 `base_url`
2. **通用性**——理论上任何 Chat Completions 兼容的 API（DeepSeek、Moonshot、Qwen、本地 Ollama 等等）都能用，改 `--target` 即可
3. **轻量**——300 行 Python，一个进程，几 MB 内存
4. **不丢功能**——工具调用、流式输出、thinking 模式全部支持

如果你也在用其他 Chat Completions 兼容的模型，把 `--target` 换成对应的地址即可。

---

*文中涉及的 DeepSeek V4 thinking 模式参考了 [deepseek-tui](https://github.com/adrianlerer/deepseek-tui) 项目的设计思路。*

