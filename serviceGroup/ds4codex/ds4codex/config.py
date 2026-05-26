"""Codex config and model-catalog helpers for ds4codex."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


DEFAULT_CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
DEFAULT_MODEL_CATALOG_PATH = Path.home() / ".codex" / "ds4codex-model-catalog.json"

DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 8099
DEFAULT_TARGET_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_THINKING = "disabled"
DEFAULT_REQUEST_TIMEOUT = 300
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"

PROVIDER_ID = "ds4codex"
SETTINGS_SECTION = "ds4codex"
ROOT_MARKER_START = "# BEGIN DS4CODEX ROOT"
ROOT_MARKER_END = "# END DS4CODEX ROOT"
SETTINGS_MARKER_START = "# BEGIN DS4CODEX SETTINGS"
SETTINGS_MARKER_END = "# END DS4CODEX SETTINGS"
PROVIDER_MARKER_START = "# BEGIN DS4CODEX PROVIDER"
PROVIDER_MARKER_END = "# END DS4CODEX PROVIDER"
DEFAULT_BEARER_PLACEHOLDER = "sk-your-deepseek-api-key"
FALLBACK_MODEL_MESSAGES = {
    "instructions_template": "",
    "instructions_variables": {
        "personality_default": "",
        "personality_friendly": "",
        "personality_pragmatic": "",
    },
}
FALLBACK_TEMPLATE_MODEL: dict[str, Any] = {
    "slug": "template",
    "display_name": "Template",
    "description": "Fallback model template bundled with ds4codex",
    "default_reasoning_level": "medium",
    "supported_reasoning_levels": [
        {"effort": "low", "description": "Fast responses with lighter reasoning"},
        {"effort": "medium", "description": "Balances speed and reasoning depth for everyday tasks"},
        {"effort": "high", "description": "Greater reasoning depth for complex problems"},
        {"effort": "xhigh", "description": "Extra high reasoning depth for complex problems"},
    ],
    "shell_type": "shell_command",
    "visibility": "list",
    "supported_in_api": True,
    "priority": 0,
    "additional_speed_tiers": [],
    "service_tiers": [],
    "availability_nux": None,
    "upgrade": None,
    "base_instructions": "",
    "model_messages": FALLBACK_MODEL_MESSAGES,
    "supports_reasoning_summaries": True,
    "default_reasoning_summary": "none",
    "support_verbosity": True,
    "default_verbosity": "low",
    "apply_patch_tool_type": "freeform",
    "web_search_tool_type": "text_and_image",
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "supports_parallel_tool_calls": True,
    "supports_image_detail_original": True,
    "context_window": 1048576,
    "max_context_window": 1048576,
    "effective_context_window_percent": 95,
    "experimental_supported_tools": [],
    "input_modalities": ["text", "image"],
    "supports_search_tool": True,
}


@dataclass(frozen=True)
class ProxySettings:
    host: str
    port: int
    target_url: str
    thinking: str
    request_timeout: int
    static_api_key: str
    api_key_env: str


@dataclass(frozen=True)
class InitResult:
    codex_config_path: Path
    model_catalog_path: Path
    updated_codex_config: bool
    wrote_model_catalog: bool
    codex_defaults_set: bool
    api_key_written: bool


def resolve_codex_config_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    """Return the Codex config path."""
    return Path(config_path).expanduser() if config_path else DEFAULT_CODEX_CONFIG_PATH


def resolve_model_catalog_path(catalog_path: str | os.PathLike[str] | None = None) -> Path:
    """Return the generated model catalog path."""
    return Path(catalog_path).expanduser() if catalog_path else DEFAULT_MODEL_CATALOG_PATH


def load_config(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load ~/.codex/config.toml if it exists."""
    path = resolve_codex_config_path(config_path)
    if not path.exists():
        return {}

    with path.open("rb") as handle:
        return tomllib.load(handle)


def resolve_proxy_settings(
    config: dict[str, Any] | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    target_url: str | None = None,
    thinking: str | None = None,
    request_timeout: int | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> ProxySettings:
    """Resolve proxy settings from CLI overrides, env, and ~/.codex/config.toml."""
    data = config or {}
    section = data.get(SETTINGS_SECTION) or {}

    resolved_api_key_env = _pick(
        api_key_env,
        os.environ.get("DS4CODEX_API_KEY_ENV"),
        DEFAULT_API_KEY_ENV,
    )

    resolved_static_api_key = _pick(
        api_key,
        os.environ.get("DS4CODEX_API_KEY"),
        "",
    )
    if resolved_static_api_key is None:
        resolved_static_api_key = ""

    return ProxySettings(
        host=str(_pick(host, os.environ.get("DS4CODEX_HOST"), DEFAULT_PROXY_HOST)),
        port=int(_pick(port, os.environ.get("DS4CODEX_PORT"), section.get("port"), DEFAULT_PROXY_PORT)),
        target_url=str(
            _pick(target_url, os.environ.get("DS4CODEX_TARGET_URL"), section.get("target_url"), DEFAULT_TARGET_URL)
        ),
        thinking=str(
            _pick(thinking, os.environ.get("DS4CODEX_THINKING"), section.get("thinking"), DEFAULT_THINKING)
        ),
        request_timeout=int(
            _pick(
                request_timeout,
                os.environ.get("DS4CODEX_REQUEST_TIMEOUT"),
                DEFAULT_REQUEST_TIMEOUT,
            )
        ),
        static_api_key=str(resolved_static_api_key),
        api_key_env=str(resolved_api_key_env),
    )


def init_all_configs(
    *,
    codex_config_path: str | os.PathLike[str] | None = None,
    model_catalog_path: str | os.PathLike[str] | None = None,
    port: int | None = None,
    apikey: str | None = None,
    force: bool = False,
) -> InitResult:
    """Initialize ~/.codex/config.toml and the generated model catalog."""
    codex_path = resolve_codex_config_path(codex_config_path)
    existing_config = load_config(codex_path)
    proxy_settings = resolve_proxy_settings(existing_config, port=port)

    catalog_path = resolve_model_catalog_path(model_catalog_path)
    wrote_catalog = write_model_catalog(catalog_path, force=force)
    updated_codex, defaults_set, api_key_written = update_codex_config(
        codex_path,
        catalog_path,
        port=proxy_settings.port,
        target_url=proxy_settings.target_url,
        thinking=proxy_settings.thinking,
        apikey=apikey,
        force=force,
    )

    return InitResult(
        codex_config_path=codex_path,
        model_catalog_path=catalog_path,
        updated_codex_config=updated_codex,
        wrote_model_catalog=wrote_catalog,
        codex_defaults_set=defaults_set,
        api_key_written=api_key_written,
    )


def write_model_catalog(
    catalog_path: str | os.PathLike[str] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Generate a model catalog JSON so `/model` can list Flash and Pro."""
    path = resolve_model_catalog_path(catalog_path)
    if path.exists() and not force:
        return False

    template_model = load_codex_template_model()
    catalog = build_model_catalog(template_model)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def load_codex_template_model() -> dict[str, Any]:
    """Load a model entry from Codex, falling back to a bundled template when needed."""
    try:
        result = subprocess.run(
            ["codex", "debug", "models", "--bundled"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, PermissionError, subprocess.CalledProcessError):
        return copy.deepcopy(FALLBACK_TEMPLATE_MODEL)

    try:
        payload = json.loads(result.stdout)
        return payload["models"][0]
    except (KeyError, IndexError, json.JSONDecodeError):
        return copy.deepcopy(FALLBACK_TEMPLATE_MODEL)


def build_model_catalog(template_model: dict[str, Any]) -> dict[str, Any]:
    """Build a Codex model catalog for DeepSeek Flash/Pro using a local template entry."""
    flash = copy.deepcopy(template_model)
    pro = copy.deepcopy(template_model)

    _apply_model_overrides(
        flash,
        slug="deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        description="DeepSeek V4 Flash via ds4codex",
        default_reasoning_level="medium",
        priority=900,
        additional_speed_tiers=["fast"],
    )
    _apply_model_overrides(
        pro,
        slug="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        description="DeepSeek V4 Pro via ds4codex",
        default_reasoning_level="high",
        priority=901,
        additional_speed_tiers=[],
    )

    return {"models": [flash, pro]}


def update_codex_config(
    config_path: str | os.PathLike[str] | None = None,
    model_catalog_path: str | os.PathLike[str] | None = None,
    *,
    port: int = DEFAULT_PROXY_PORT,
    target_url: str = DEFAULT_TARGET_URL,
    thinking: str = DEFAULT_THINKING,
    apikey: str | None = None,
    force: bool = False,
) -> tuple[bool, bool, bool]:
    """Write or update the user's Codex config with ds4codex integration."""
    path = resolve_codex_config_path(config_path)
    catalog_path = resolve_model_catalog_path(model_catalog_path)

    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    existing_config: dict[str, Any] = {}
    if existing_text.strip():
        try:
            existing_config = tomllib.loads(existing_text)
        except Exception:
            existing_config = {}

    provider = (existing_config.get("model_providers") or {}).get(PROVIDER_ID) or {}
    provider_token = str(_pick(apikey, provider.get("experimental_bearer_token"), DEFAULT_BEARER_PLACEHOLDER))
    provider_exists = bool(provider)
    catalog_exists = "model_catalog_json" in existing_config
    settings_exists = SETTINGS_SECTION in existing_config

    updated_text = existing_text
    if not updated_text.strip():
        updated_text = render_new_codex_config(
            catalog_path,
            port=port,
            target_url=target_url,
            thinking=thinking,
            provider_token=provider_token,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated_text, encoding="utf-8")
        return True, True, apikey is not None

    if ROOT_MARKER_START in updated_text:
        updated_text = replace_marked_block(
            updated_text,
            ROOT_MARKER_START,
            ROOT_MARKER_END,
            render_root_block(catalog_path, set_defaults=False),
        )
    elif not catalog_exists:
        updated_text = inject_root_block(updated_text, render_root_block(catalog_path, set_defaults=False))

    settings_block = render_settings_block(port=port, target_url=target_url, thinking=thinking)
    if SETTINGS_MARKER_START in updated_text:
        updated_text = replace_marked_block(
            updated_text,
            SETTINGS_MARKER_START,
            SETTINGS_MARKER_END,
            settings_block,
        )
    elif not settings_exists:
        updated_text = append_block(updated_text, settings_block)

    provider_block = render_provider_block(port=port, provider_token=provider_token)
    if PROVIDER_MARKER_START in updated_text:
        updated_text = replace_marked_block(
            updated_text,
            PROVIDER_MARKER_START,
            PROVIDER_MARKER_END,
            provider_block,
        )
    elif not provider_exists:
        updated_text = append_block(updated_text, provider_block)

    if updated_text != existing_text or force:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated_text, encoding="utf-8")
        return True, False, apikey is not None

    return False, False, False


def render_new_codex_config(
    model_catalog_path: Path,
    *,
    port: int,
    target_url: str,
    thinking: str,
    provider_token: str,
) -> str:
    """Render a fresh Codex config with ds4codex as the default provider."""
    blocks = [
        render_root_block(model_catalog_path, set_defaults=True),
        render_settings_block(port=port, target_url=target_url, thinking=thinking),
        render_provider_block(port=port, provider_token=provider_token),
    ]
    return "\n\n".join(blocks) + "\n"


def render_root_block(model_catalog_path: Path, *, set_defaults: bool) -> str:
    """Render the managed root block for Codex config."""
    lines = [ROOT_MARKER_START]
    if set_defaults:
        lines.extend(
            [
                'model = "deepseek-v4-flash"',
                f'model_provider = "{PROVIDER_ID}"',
                "model_context_window = 1048576",
            ]
        )
    lines.append(f'model_catalog_json = "{model_catalog_path}"')
    if not set_defaults:
        lines.append('# Optional: set `model = "deepseek-v4-flash"` and `model_provider = "ds4codex"` if needed.')
    lines.append(ROOT_MARKER_END)
    return "\n".join(lines)


def render_settings_block(*, port: int, target_url: str, thinking: str) -> str:
    """Render the managed ds4codex settings block inside ~/.codex/config.toml."""
    return "\n".join(
        [
            SETTINGS_MARKER_START,
            f"[{SETTINGS_SECTION}]",
            f"port = {port}",
            f'target_url = "{target_url}"',
            f'thinking = "{thinking}"',
            SETTINGS_MARKER_END,
        ]
    )


def render_provider_block(*, port: int, provider_token: str) -> str:
    """Render the managed provider block for Codex config."""
    return "\n".join(
        [
            PROVIDER_MARKER_START,
            f"[model_providers.{PROVIDER_ID}]",
            'name = "DeepSeek via ds4codex"',
            f'base_url = "http://127.0.0.1:{port}/v1"',
            'wire_api = "responses"',
            f'experimental_bearer_token = "{provider_token}"',
            PROVIDER_MARKER_END,
        ]
    )


def inject_root_block(text: str, block: str) -> str:
    """Insert a root-level block before the first TOML table."""
    lines = text.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if line.lstrip().startswith("["):
            insert_at = index
            break
    else:
        insert_at = len(lines)

    prefix = lines[:insert_at]
    suffix = lines[insert_at:]

    merged: list[str] = []
    if prefix:
        merged.extend(prefix)
        if prefix[-1].strip():
            merged.append("")
    merged.extend(block.splitlines())
    if suffix:
        merged.append("")
        merged.extend(suffix)
    return "\n".join(merged).rstrip() + "\n"


def append_block(text: str, block: str) -> str:
    """Append a managed block at the end of the config file."""
    base = text.rstrip()
    if base:
        return f"{base}\n\n{block}\n"
    return f"{block}\n"


def replace_marked_block(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """Replace a managed block between markers."""
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    return f"{text[:start]}{replacement}{text[end:]}"


def _apply_model_overrides(
    model: dict[str, Any],
    *,
    slug: str,
    display_name: str,
    description: str,
    default_reasoning_level: str,
    priority: int,
    additional_speed_tiers: list[str],
) -> None:
    model["slug"] = slug
    model["display_name"] = display_name
    model["description"] = description
    model["context_window"] = 1048576
    model["max_context_window"] = 1048576
    model["effective_context_window_percent"] = 95
    model["default_reasoning_level"] = default_reasoning_level
    model["supported_reasoning_levels"] = [
        {"effort": "low", "description": "Fast responses with lighter reasoning"},
        {"effort": "medium", "description": "Balances speed and reasoning depth for everyday tasks"},
        {"effort": "high", "description": "Greater reasoning depth for complex problems"},
        {"effort": "xhigh", "description": "Extra high reasoning depth for complex problems"},
    ]
    model["priority"] = priority
    model["additional_speed_tiers"] = additional_speed_tiers
    model["service_tiers"] = []
    model["supported_in_api"] = True
    model["visibility"] = "list"


def _pick(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value
    return None
