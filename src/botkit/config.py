"""Configuration and local plugin loading."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Protocol


class ConfigError(ValueError):
    """Configuration is missing or invalid. Never include secret values in messages."""


class TextPlugin(Protocol):
    def on_text(self, message: "Incoming") -> str | None: ...


@dataclass(frozen=True)
class Incoming:
    chat_id: int
    user_id: int | None
    text: str


@dataclass(frozen=True)
class BotSettings:
    name: str
    start_message: str
    fallback_message: str
    plugin_file: str
    token_env: str
    poll_timeout: int


def _nonempty(table: dict, key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Expected a nonempty string: {key}")
    return value


def _reply_setting(table: dict, key: str) -> str:
    value = _nonempty(table, key)
    if len(value) > 4096:
        raise ConfigError(f"{key} must not exceed 4096 characters")
    return value


def load_settings(path: Path) -> BotSettings:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read bot config: {path}") from exc
    bot = raw.get("bot")
    telegram = raw.get("telegram")
    if not isinstance(bot, dict) or not isinstance(telegram, dict):
        raise ConfigError("Config needs [bot] and [telegram] tables")
    plugin_file = _nonempty(bot, "plugin")
    if Path(plugin_file).name != plugin_file or not plugin_file.endswith(".py"):
        raise ConfigError("[bot].plugin must be a .py filename in the bot folder")
    token_env = _nonempty(telegram, "token_env")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", token_env):
        raise ConfigError("[telegram].token_env must be an uppercase env variable name")
    timeout = telegram.get("poll_timeout", 25)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 50:
        raise ConfigError("[telegram].poll_timeout must be an integer from 1 to 50")
    return BotSettings(
        name=_nonempty(bot, "name"),
        start_message=_reply_setting(bot, "start_message"),
        fallback_message=_reply_setting(bot, "fallback_message"),
        plugin_file=plugin_file,
        token_env=token_env,
        poll_timeout=timeout,
    )


def load_plugin(config_path: Path, settings: BotSettings) -> TextPlugin:
    """Load trusted, user-owned code from beside bot.toml."""
    plugin_path = Path(config_path).parent / settings.plugin_file
    if not plugin_path.is_file():
        raise ConfigError(f"Plugin file is missing: {plugin_path}")
    spec = importlib.util.spec_from_file_location("_botkit_local_plugin", plugin_path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Cannot load plugin: {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_type = getattr(module, "Plugin", None)
    if not isinstance(plugin_type, type):
        raise ConfigError("Plugin file must define a Plugin class")
    plugin = plugin_type()
    if not callable(getattr(plugin, "on_text", None)):
        raise ConfigError("Plugin must define on_text(message)")
    return plugin


def load_token(config_path: Path, env_name: str) -> str:
    """Read an environment variable or a local .env file, without logging its value."""
    token = os.environ.get(env_name, "").strip()
    if token:
        return token
    env_path = Path(config_path).parent / ".env"
    if env_path.is_file():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ConfigError("Cannot read local .env file") from exc
        for line in lines:
            if line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == env_name:
                token = value.strip().strip('"').strip("'")
                if token:
                    return token
    raise ConfigError(f"Set {env_name} in the environment or in a local .env file")
