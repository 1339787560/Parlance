#!/usr/bin/env python3
"""
DeepSeek V4 Token Statistics Tool.
Real-time token usage & cache hit rate tracking.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()

# --- Config ---
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
CONFIG_DIR = Path.home() / ".deepseek_stats"
HISTORY_FILE = CONFIG_DIR / "history.json"

# Pricing (per 1M tokens, RMB) — DeepSeek v4 Pro
PRICING = {
    "cache_hit": 0.025,
    "cache_miss": 3,
    "completion": 6,
}


@dataclass
class RequestRecord:
    timestamp: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0
    prompt_characters: int = 0
    completion_characters: int = 0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hit_tokens + self.cache_miss_tokens
        return (self.cache_hit_tokens / total * 100) if total > 0 else 0.0

    @property
    def cost(self) -> float:
        return (
            self.cache_hit_tokens * PRICING["cache_hit"]
            + self.cache_miss_tokens * PRICING["cache_miss"]
            + self.completion_tokens * PRICING["completion"]
        ) / 1_000_000


@dataclass
class SessionStats:
    requests: list = field(default_factory=list)

    @property
    def total_requests(self) -> int:
        return len(self.requests)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.requests)

    @property
    def total_completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.requests)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.requests)

    @property
    def total_cache_hit(self) -> int:
        return sum(r.cache_hit_tokens for r in self.requests)

    @property
    def total_cache_miss(self) -> int:
        return sum(r.cache_miss_tokens for r in self.requests)

    @property
    def cache_hit_rate(self) -> float:
        total = self.total_cache_hit + self.total_cache_miss
        return (self.total_cache_hit / total * 100) if total > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (
            sum(r.latency_ms for r in self.requests) / self.total_requests
            if self.total_requests > 0
            else 0.0
        )

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.requests)

    @property
    def cost_saved_by_cache(self) -> float:
        """How much $ saved vs if all cache-hit tokens were cache-miss."""
        return self.total_cache_hit * (PRICING["cache_miss"] - PRICING["cache_hit"]) / 1_000_000


class DeepSeekStatsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.session = SessionStats()
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=180.0,
        )

    def chat(self, messages: list, temperature: float = 0.7, **kwargs) -> tuple:
        """Non-streaming chat. Returns (response_text, RequestRecord)."""
        prompt_chars = sum(len(m.get("content", "")) for m in messages)

        start = time.time()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            **kwargs,
        }
        resp = self.client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        elapsed_ms = int((time.time() - start) * 1000)

        usage = data.get("usage", {})
        choice = data["choices"][0]
        content = choice["message"].get("content", "")

        record = RequestRecord(
            timestamp=datetime.now().isoformat(),
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cache_hit_tokens=usage.get("prompt_cache_hit_tokens", 0),
            cache_miss_tokens=usage.get("prompt_cache_miss_tokens", 0),
            reasoning_tokens=usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
            latency_ms=elapsed_ms,
            prompt_characters=prompt_chars,
            completion_characters=len(content),
        )

        self.session.requests.append(record)
        return content, record

    def chat_stream(self, messages: list, temperature: float = 0.7, **kwargs) -> tuple:
        """Streaming chat. Returns (full_text, RequestRecord)."""
        prompt_chars = sum(len(m.get("content", "")) for m in messages)

        start = time.time()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            **kwargs,
        }

        content_chunks = []
        usage = {}

        with self.client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        content_chunks.append(delta["content"])

                    # Usage comes in final chunk
                    if "usage" in chunk:
                        usage = chunk["usage"]

        elapsed_ms = int((time.time() - start) * 1000)
        full_content = "".join(content_chunks)

        record = RequestRecord(
            timestamp=datetime.now().isoformat(),
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cache_hit_tokens=usage.get("prompt_cache_hit_tokens", 0),
            cache_miss_tokens=usage.get("prompt_cache_miss_tokens", 0),
            reasoning_tokens=usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
            latency_ms=elapsed_ms,
            prompt_characters=prompt_chars,
            completion_characters=len(full_content),
        )

        self.session.requests.append(record)
        return full_content, record

    def print_request_table(self, record: RequestRecord):
        """Rich table for single request."""
        table = Table(show_header=False, box=box.ROUNDED, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=18)
        table.add_column("Value", style="white")

        table.add_row("Request #", str(self.session.total_requests))
        table.add_row("Model", record.model)
        table.add_row("Latency", f"{record.latency_ms}ms")
        table.add_row("Prompt Tokens", f"{record.prompt_tokens:,}")
        table.add_row("Completion Tokens", f"{record.completion_tokens:,}")
        table.add_row("Total Tokens", f"{record.total_tokens:,}")

        # Cache section
        total_cache = record.cache_hit_tokens + record.cache_miss_tokens
        if total_cache > 0:
            rate_color = "green" if record.cache_hit_rate > 50 else "yellow" if record.cache_hit_rate > 0 else "red"
            table.add_row("Cache Hit", f"{record.cache_hit_tokens:,} tokens ({record.cache_hit_tokens/total_cache*100:.1f}%)")
            table.add_row("Cache Miss", f"{record.cache_miss_tokens:,} tokens ({record.cache_miss_tokens/total_cache*100:.1f}%)")
            table.add_row(
                "Cache Hit Rate",
                f"[{rate_color}]{record.cache_hit_rate:.1f}%[/{rate_color}]",
            )

        if record.reasoning_tokens > 0:
            table.add_row("Reasoning Tokens", f"{record.reasoning_tokens:,}")

        table.add_row("Cost", f"${record.cost:.6f}")

        console.print()
        console.print(Panel(table, title="[bold]📊 Request Stats[/bold]", border_style="blue"))
        console.print()

    def print_session_table(self):
        """Rich table for session summary."""
        s = self.session
        if s.total_requests == 0:
            console.print("[yellow]No requests in this session.[/yellow]")
            return

        table = Table(show_header=False, box=box.ROUNDED, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=22)
        table.add_column("Value", style="white")

        table.add_row("Total Requests", str(s.total_requests))
        table.add_row("Total Prompt Tokens", f"{s.total_prompt_tokens:,}")
        table.add_row("Total Completion Tokens", f"{s.total_completion_tokens:,}")
        table.add_row("Total Tokens", f"{s.total_tokens:,}")
        table.add_row("Total Cache Hit", f"{s.total_cache_hit:,}")
        table.add_row("Total Cache Miss", f"{s.total_cache_miss:,}")

        rate = s.cache_hit_rate
        rate_color = "green" if rate > 50 else "yellow" if rate > 0 else "red"
        table.add_row(
            "Overall Cache Hit Rate",
            f"[{rate_color}]{rate:.1f}%[/{rate_color}]",
        )

        table.add_row("Avg Latency", f"{s.avg_latency_ms:.0f}ms")

        table.add_row(
            "Total Cost",
            f"${s.total_cost:.6f}",
        )
        table.add_row(
            "Saved by Cache",
            f"[green]${s.cost_saved_by_cache:.6f}[/green]",
        )

        # Per-request breakdown table
        if s.total_requests > 1:
            detail = Table(box=box.SIMPLE, padding=(0, 1))
            detail.add_column("#", style="dim", width=3)
            detail.add_column("Prompt", justify="right", width=8)
            detail.add_column("Completion", justify="right", width=10)
            detail.add_column("Total", justify="right", width=8)
            detail.add_column("Cache Hit", justify="right", width=8)
            detail.add_column("Cache Rate", justify="right", width=9)
            detail.add_column("Latency", justify="right", width=8)

            for i, r in enumerate(s.requests, 1):
                rate_str = f"{r.cache_hit_rate:.0f}%" if (r.cache_hit_tokens + r.cache_miss_tokens) > 0 else "-"
                detail.add_row(
                    str(i),
                    f"{r.prompt_tokens:,}",
                    f"{r.completion_tokens:,}",
                    f"{r.total_tokens:,}",
                    f"{r.cache_hit_tokens:,}",
                    rate_str,
                    f"{r.latency_ms}ms",
                )

            console.print()
            console.print(Panel(table, title="[bold]📈 Session Summary[/bold]", border_style="green"))
            console.print()
            console.print(Panel(detail, title="[bold]📋 Per-Request Breakdown[/bold]", border_style="blue"))
        else:
            console.print()
            console.print(Panel(table, title="[bold]📈 Session Summary[/bold]", border_style="green"))

        console.print()


def load_history() -> list:
    """Load request history from disk."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(session: SessionStats):
    """Append session requests to history file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()
    for r in session.requests:
        history.append({
            "timestamp": r.timestamp,
            "model": r.model,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "cache_hit_tokens": r.cache_hit_tokens,
            "cache_miss_tokens": r.cache_miss_tokens,
            "latency_ms": r.latency_ms,
        })
    # Keep last 1000 entries
    history = history[-1000:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def get_api_key() -> str:
    """Get API key from env or config."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    config_file = CONFIG_DIR / "api_key"
    if config_file.exists():
        return config_file.read_text().strip()
    return ""


def cmd_chat(args):
    """Single chat command or interactive session."""
    api_key = get_api_key()
    if not api_key:
        console.print("[red]Error: DEEPSEEK_API_KEY not set.[/red]")
        console.print("  Set env:  $env:DEEPSEEK_API_KEY = 'sk-...'")
        console.print(f"  Or save:  echo 'sk-...' > {CONFIG_DIR / 'api_key'}")
        sys.exit(1)

    client = DeepSeekStatsClient(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
    )

    system_msg = None
    if args.system:
        system_msg = {"role": "system", "content": args.system}

    messages = []
    if system_msg:
        messages.append(system_msg)

    if args.interactive:
        console.print(
            Panel(
                "[bold cyan]DeepSeek V4 Token Statistics Console[/bold cyan]\n"
                "Type your messages. Commands:\n"
                "  /stats    - Show session stats\n"
                "  /clear    - Clear conversation history\n"
                "  /save     - Save history to disk\n"
                "  /quit     - Exit",
                border_style="cyan",
            )
        )

        while True:
            try:
                prompt = console.input("\n[bold green]You[/bold green] > ")
            except (EOFError, KeyboardInterrupt):
                break

            if not prompt.strip():
                continue

            if prompt.startswith("/"):
                cmd = prompt[1:].strip().lower()
                if cmd in ("quit", "exit", "q"):
                    break
                elif cmd == "stats":
                    client.print_session_table()
                    continue
                elif cmd == "clear":
                    messages.clear()
                    if system_msg:
                        messages.append(system_msg)
                    console.print("[dim]Conversation cleared.[/dim]")
                    continue
                elif cmd == "save":
                    save_history(client.session)
                    console.print("[green]History saved.[/green]")
                    continue
                else:
                    console.print(f"[yellow]Unknown command: /{cmd}[/yellow]")
                    continue

            messages.append({"role": "user", "content": prompt})

            with console.status("[cyan]Thinking..."):
                try:
                    if args.stream:
                        content, record = client.chat_stream(messages)
                    else:
                        content, record = client.chat(messages)

                    client.print_request_table(record)
                    console.print(f"[bold cyan]Assistant[/bold cyan] > {content}")
                    messages.append({"role": "assistant", "content": content})
                except httpx.HTTPStatusError as e:
                    console.print(f"[red]API Error: {e.response.status_code} - {e.response.text}[/red]")
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")

        console.print("\n[bold]Session ended.[/bold]")
        client.print_session_table()
        save_history(client.session)

    else:
        # Single message mode
        if not args.prompt:
            console.print("[red]Error: prompt required. Use --prompt or -p.[/red]")
            sys.exit(1)

        messages.append({"role": "user", "content": args.prompt})

        with console.status("[cyan]Thinking..."):
            try:
                if args.stream:
                    content, record = client.chat_stream(messages)
                else:
                    content, record = client.chat(messages)

                client.print_request_table(record)
                console.print(f"[bold cyan]Assistant[/bold cyan] > {content}")
                save_history(client.session)
            except httpx.HTTPStatusError as e:
                console.print(f"[red]API Error: {e.response.status_code} - {e.response.text}[/red]")
                sys.exit(1)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                sys.exit(1)


def cmd_history(args):
    """Display historical stats."""
    history = load_history()
    if not history:
        console.print("[yellow]No history found.[/yellow]")
        return

    # Compute aggregate
    total_req = len(history)
    total_prompt = sum(r["prompt_tokens"] for r in history)
    total_comp = sum(r["completion_tokens"] for r in history)
    total_tok = sum(r["total_tokens"] for r in history)
    total_hit = sum(r["cache_hit_tokens"] for r in history)
    total_miss = sum(r["cache_miss_tokens"] for r in history)
    hit_rate = (total_hit / (total_hit + total_miss) * 100) if (total_hit + total_miss) > 0 else 0.0

    table = Table(show_header=False, box=box.ROUNDED)
    table.add_column("Metric", style="cyan", width=22)
    table.add_column("Value", style="white")
    table.add_row("Total Historical Requests", str(total_req))
    table.add_row("Total Prompt Tokens", f"{total_prompt:,}")
    table.add_row("Total Completion Tokens", f"{total_comp:,}")
    table.add_row("Total Tokens", f"{total_tok:,}")
    table.add_row("Total Cache Hit", f"{total_hit:,}")
    table.add_row("Total Cache Miss", f"{total_miss:,}")
    table.add_row("Overall Cache Hit Rate", f"{hit_rate:.1f}%")
    console.print(Panel(table, title="[bold]📈 Historical Stats[/bold]", border_style="green"))

    # Show recent requests
    recent = history[-10:]
    detail = Table(box=box.SIMPLE, padding=(0, 1))
    detail.add_column("Time", style="dim", width=16)
    detail.add_column("Prompt", justify="right", width=8)
    detail.add_column("Comp", justify="right", width=8)
    detail.add_column("Cache Hit", justify="right", width=8)
    detail.add_column("Rate", justify="right", width=6)
    detail.add_column("Latency", justify="right", width=8)

    for r in reversed(recent):
        ts = r["timestamp"][11:19] if len(r["timestamp"]) > 19 else r["timestamp"]
        tot = r["cache_hit_tokens"] + r["cache_miss_tokens"]
        rate_str = f"{r['cache_hit_tokens']/tot*100:.0f}%" if tot > 0 else "-"
        detail.add_row(ts, f"{r['prompt_tokens']:,}", f"{r['completion_tokens']:,}", f"{r['cache_hit_tokens']:,}", rate_str, f"{r['latency_ms']}ms")

    console.print()
    console.print(Panel(detail, title="[bold]📋 Recent Requests[/bold]", border_style="blue"))
    console.print()


def cmd_cost_estimate(args):
    """Estimate cost for a given token count."""
    prompt = args.prompt_tokens or 0
    completion = args.completion_tokens or 0
    cache_hit_rate = args.cache_hit_rate or 0

    miss = prompt * (1 - cache_hit_rate / 100)
    hit = prompt * (cache_hit_rate / 100)

    cost_miss = miss * PRICING["cache_miss"] / 1_000_000
    cost_hit = hit * PRICING["cache_hit"] / 1_000_000
    cost_comp = completion * PRICING["completion"] / 1_000_000
    total = cost_miss + cost_hit + cost_comp

    table = Table(show_header=False, box=box.ROUNDED)
    table.add_column("Item", style="cyan", width=20)
    table.add_column("Tokens", justify="right", width=12)
    table.add_column("Cost", justify="right", width=12)

    table.add_row("Prompt (miss)", f"{miss:,.0f}", f"${cost_miss:.6f}")
    table.add_row("Prompt (hit)", f"{hit:,.0f}", f"${cost_hit:.6f}")
    table.add_row("Completion", f"{completion:,}", f"${cost_comp:.6f}")
    table.add_row("")
    table.add_row("Total", f"{prompt + completion:,}", f"[bold]${total:.6f}[/bold]")

    console.print(Panel(table, title="[bold]💰 Cost Estimate[/bold]", border_style="yellow"))


def main():
    parser = argparse.ArgumentParser(
        description="DeepSeek V4 Token Statistics Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s chat -p "Hello"
  %(prog)s chat --interactive
  %(prog)s chat -p "Explain AI" --stream
  %(prog)s chat -i -s "You are a poet"
  %(prog)s history
  %(prog)s cost --prompt 1000 --completion 500 --cache-hit-rate 60
        """,
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # chat
    chat_p = sub.add_parser("chat", help="Chat with DeepSeek")
    chat_p.add_argument("-p", "--prompt", help="Single prompt message")
    chat_p.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    chat_p.add_argument("-s", "--system", help="System prompt")
    chat_p.add_argument("--stream", action="store_true", help="Use streaming")
    chat_p.add_argument("--temperature", type=float, default=0.7, help="Temperature (default: 0.7)")
    chat_p.set_defaults(func=cmd_chat)

    # history
    hist_p = sub.add_parser("history", help="Show historical token usage")
    hist_p.set_defaults(func=cmd_history)

    # cost estimate
    cost_p = sub.add_parser("cost", help="Estimate cost for token usage")
    cost_p.add_argument("--prompt", dest="prompt_tokens", type=int, default=0, help="Prompt tokens")
    cost_p.add_argument("--completion", dest="completion_tokens", type=int, default=0, help="Completion tokens")
    cost_p.add_argument("--cache-hit-rate", dest="cache_hit_rate", type=float, default=0, help="Cache hit rate %")
    cost_p.set_defaults(func=cmd_cost_estimate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
