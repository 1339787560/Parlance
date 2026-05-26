"""Click CLI for ds4codex."""

from __future__ import annotations

from pathlib import Path

import click

from .config import (
    init_all_configs,
    load_config,
    resolve_codex_config_path,
    resolve_proxy_settings,
)
from .proxy import run_proxy


@click.group()
def main() -> None:
    """ds4codex - Responses API proxy for Codex."""


@main.command("init", short_help="Initialize ds4codex and Codex config files")
@click.option(
    "--config-path",
    "--codex-config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom ~/.codex/config.toml path",
)
@click.option(
    "--model-catalog-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom generated model catalog JSON path",
)
@click.option("--port", type=int, default=None, help="Default ds4codex port to write into ~/.codex/config.toml")
@click.option("--apikey", "--api-key", default=None, help="Write upstream bearer token into ~/.codex/config.toml")
@click.option("--force", is_flag=True, help="Overwrite managed ds4codex artifacts")
def init_command(
    config_path: Path | None,
    model_catalog_path: Path | None,
    port: int | None,
    apikey: str | None,
    force: bool,
) -> None:
    """Initialize ~/.codex/config.toml and the generated model catalog."""
    result = init_all_configs(
        codex_config_path=config_path,
        model_catalog_path=model_catalog_path,
        port=port,
        apikey=apikey,
        force=force,
    )

    click.echo(f"Codex config: {result.codex_config_path}")
    click.echo(f"Model catalog: {result.model_catalog_path}")
    click.echo("")
    if result.api_key_written:
        click.echo("API key was written into the managed provider block.")
    else:
        click.echo("Next: edit ~/.codex/config.toml and replace `sk-your-deepseek-api-key`, then run `ds4codex run`.")
    if not result.codex_defaults_set:
        click.echo("Existing ~/.codex/config.toml was preserved; ds4codex blocks were added or refreshed safely.")


@main.command("run", short_help="Start the local proxy server")
@click.option(
    "--config-path",
    "--codex-config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom ~/.codex/config.toml path",
)
@click.option("--host", default=None, help="Listen host override")
@click.option("--port", type=int, default=None, help="Listen port override")
@click.option("--target-url", default=None, help="Upstream chat completions URL override")
@click.option("--thinking", default=None, help="Default thinking mode override")
@click.option("--request-timeout", type=int, default=None, help="HTTP timeout in seconds")
@click.option("--api-key", default=None, help="Static upstream API key override")
@click.option("--api-key-env", default=None, help="Env var name to read the upstream API key from")
@click.option("--log-level", default="INFO", show_default=True, help="Python logging level")
def run_command(
    config_path: Path | None,
    host: str | None,
    port: int | None,
    target_url: str | None,
    thinking: str | None,
    request_timeout: int | None,
    api_key: str | None,
    api_key_env: str | None,
    log_level: str,
) -> None:
    """Run the proxy server."""
    path = resolve_codex_config_path(config_path)
    config = load_config(path)
    settings = resolve_proxy_settings(
        config,
        host=host,
        port=port,
        target_url=target_url,
        thinking=thinking,
        request_timeout=request_timeout,
        api_key=api_key,
        api_key_env=api_key_env,
    )
    run_proxy(settings, log_level=log_level)
