import time
import json
import os
import glob
from openai import OpenAI
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# ================= 配置区域 =================
ANTHROPIC_BASE_URL = "http://aiapi.tcy365.net:82/" # 填写你的 URL
ANTHROPIC_AUTH_TOKEN = ""     # 填写你的 Token
# doubao-seed-2.0-code、doubao-seed-2.0-pro、
# step3.5-flash-fp8
MODELS = [
    "deepseek-v3.2", 
    "deepseek-v3.2-thinking", 
    "glm-4.7", "glm-5", "glm-5.1", 
    "kimi-k2.5", 
    "MiniMax-M2.1", "MiniMax-M2.5", "MiniMax-M2.7",
    "doubao-seed-2.0-code","doubao-seed-2.0-pro",
    "step3.5-flash-fp8",
    "gpt-5.5",
    "claude-opus-4-7",
]

SHORT_PROMPT = "你好，请用一句话介绍你自己并输出当前的系统时间。"
LONG_PROMPT = "请仔细阅读以下长文本，并在最后提取出本文的三个核心观点：\n" + ("人类的科技发展日新月异，人工智能正在改变各行各业的运作方式。" * 300)

console = Console()
# ============================================

# 智能清洗 URL：无论你填的是包含 /v1/messages 还是裸域名，自动适配为标准格式
cleaned_url = ANTHROPIC_BASE_URL.rstrip('/')
if cleaned_url.endswith('/v1/messages'):
    cleaned_url = cleaned_url.replace('/v1/messages', '/v1')
elif not cleaned_url.endswith('/v1'):
    cleaned_url = f"{cleaned_url}/v1"

# 使用官方客户端：底层为 httpx，支持 HTTP/2，完美伪装，杜绝 502
client = OpenAI(
    api_key=ANTHROPIC_AUTH_TOKEN,
    base_url=cleaned_url
)

def measure_performance(model_name: str, prompt: str):
    start_time = time.time()
    first_token_time = None
    output_tokens = 0
    
    try:
        # 发起官方流式请求
        stream = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            max_tokens=1024,
            stream_options={"include_usage": True} # 要求代理返回精确的 token 消耗
        )
        
        chunk_count = 0
        for chunk in stream:
            # 捕获首字时间
            if chunk.choices and chunk.choices[0].delta.content:
                chunk_count += 1
                if first_token_time is None:
                    first_token_time = time.time()
            
            # 捕获 Token 消耗
            if chunk.usage:
                output_tokens = chunk.usage.completion_tokens

        end_time = time.time()
        
        # 兼容处理：如果代理没传回 usage，用 chunk 数量兜底
        if output_tokens == 0:
            output_tokens = chunk_count

        ttft = first_token_time - start_time if first_token_time else 0
        generation_time = end_time - first_token_time if first_token_time else 0
        tps = output_tokens / generation_time if generation_time > 0 else 0
        
        return {
            "error": None,
            "ttft": ttft,
            "tps": tps,
        }
        
    except Exception as e:
        error_msg = str(e)
        if "502" in error_msg:
            error_msg = "上游通道未配置或不可用 (502)"
        return {"error": error_msg[:40]}

BENCHMARK_DIR = os.path.join(os.getcwd(), 'src', 'cache', 'benchmarks')
MAX_BENCHMARK_FILES = 5

def run_benchmark(return_results=False):
    """运行基准测试。return_results=True 时返回结果列表而不打印表格。"""
    if return_results:
        results = []
        for model in MODELS:
            short_res = measure_performance(model, SHORT_PROMPT)
            if not short_res.get("error"):
                long_res = measure_performance(model, LONG_PROMPT)
            else:
                long_res = {"error": "Skipped"}
            results.append({"model": model, "short": short_res, "long": long_res})
        return results

    console.print("\n[bold cyan]🚀 LLM API 性能基准测试 (基于标准 SDK)[/bold cyan]")
    console.print(f"🔗 实际测试节点: {cleaned_url}")
    console.print(f"📦 队列模型数: {len(MODELS)}\n")

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        for model in MODELS:
            task = progress.add_task(f"正在测试: [bold yellow]{model}[/bold yellow] ...", total=2)

            progress.update(task, description=f"[{model}] 测算短文本(TTFT/TPS)...")
            short_res = measure_performance(model, SHORT_PROMPT)

            if not short_res.get("error"):
                progress.update(task, description=f"[{model}] 测算长文本(10k)延迟衰减...")
                long_res = measure_performance(model, LONG_PROMPT)
            else:
                long_res = {"error": "Skipped"}

            results.append({"model": model, "short": short_res, "long": long_res})
            progress.advance(task, 2)

    # 绘制表格
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("模型名称", style="cyan")
    table.add_column("状态", justify="center")
    table.add_column("首字延迟\n(TTFT)", justify="right")
    table.add_column("生成速度\n(TPS)", justify="right")
    table.add_column("长文本(10k)\n首字延迟", justify="right")
    table.add_column("长文延迟\n衰减倍率", justify="right")

    for res in results:
        m, s, l = res["model"], res["short"], res["long"]

        if s.get("error"):
            table.add_row(m, "[red]Failed[/red]", f"[dim]{s['error']}[/dim]", "-", "-", "-")
            continue

        ttft_str = f"[green]{s['ttft']:.2f} s[/green]"
        tps_str = f"[bold yellow]{s['tps']:.1f} t/s[/bold yellow]"

        if l.get("error"):
            table.add_row(m, "[yellow]Partial[/yellow]", ttft_str, tps_str, "[red]Failed[/red]", "-")
        else:
            long_ttft_str = f"{l['ttft']:.2f} s"
            ratio = l['ttft'] / s['ttft'] if s['ttft'] > 0 else 0
            color = "green" if ratio <= 1.5 else "yellow" if ratio <= 3 else "red"

            table.add_row(m, "[green]Success[/green]", ttft_str, tps_str, long_ttft_str, f"[{color}]{ratio:.1f}x[/{color}]")

    console.print(table)


def analyze_results(results):
    """将 benchmark 结果发送给 glm-5.1 进行分析，返回分析文本。"""
    try:
        summary_lines = []
        for r in results:
            m, s, l = r["model"], r["short"], r["long"]
            if s.get("error"):
                summary_lines.append(f"- {m}: 测试失败({s['error']})")
                continue
            line = f"- {m}: TTFT={s['ttft']:.2f}s, TPS={s['tps']:.1f}t/s"
            if not l.get("error"):
                ratio = l['ttft'] / s['ttft'] if s['ttft'] > 0 else 0
                line += f", 长文本TTFT={l['ttft']:.2f}s, 衰减={ratio:.1f}x"
            else:
                line += ", 长文本测试失败"
            summary_lines.append(line)

        prompt = (
            "你是一位 LLM API 性能分析专家。以下是本次聚合服务 API 的 benchmark 测试结果，请用简洁的中文进行分析，包括：\n"
            "1. 整体表现概览\n"
            "2. 各模型优劣势排名\n"
            "3. 延迟衰减分析\n"
            "4. 推荐使用建议\n\n"
            + "\n".join(summary_lines)
        )

        resp = client.chat.completions.create(
            model="glm-5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"分析请求失败: {str(e)[:100]}"


def save_benchmark(results, analysis=None):
    """将测试结果保存为 benchmark_{time}.json，并清理旧文件只保留最近5个。"""
    if not os.path.exists(BENCHMARK_DIR):
        os.makedirs(BENCHMARK_DIR)

    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"benchmark_{timestamp}.json"
    filepath = os.path.join(BENCHMARK_DIR, filename)

    data = {
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "models": results,
        "analysis": analysis or ""
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 清理旧文件，只保留最近 MAX_BENCHMARK_FILES 个
    existing = sorted(glob.glob(os.path.join(BENCHMARK_DIR, 'benchmark_*.json')))
    while len(existing) > MAX_BENCHMARK_FILES:
        os.remove(existing.pop(0))

    return filepath


def get_latest_benchmark():
    """获取最新的 benchmark 数据。"""
    if not os.path.exists(BENCHMARK_DIR):
        return None
    files = sorted(glob.glob(os.path.join(BENCHMARK_DIR, 'benchmark_*.json')))
    if not files:
        return None
    with open(files[-1], 'r', encoding='utf-8') as f:
        return json.load(f)


def get_all_benchmarks():
    """获取所有 benchmark 数据列表（按时间升序）。"""
    if not os.path.exists(BENCHMARK_DIR):
        return []
    files = sorted(glob.glob(os.path.join(BENCHMARK_DIR, 'benchmark_*.json')))
    results = []
    for fp in files:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data['filename'] = os.path.basename(fp)
            results.append(data)
    return results

if __name__ == "__main__":
    run_benchmark()