"""Generate a bot folder without overwriting user files."""

from __future__ import annotations

import json
from pathlib import Path
import re


class ScaffoldError(ValueError):
    pass


ECHO_PLUGIN = '''from botkit.config import Incoming


class Plugin:
    def on_text(self, message: Incoming) -> str | None:
        # Replace this method with your bot's own behavior when needed.
        return f"Вы написали: {message.text}"
'''

TT_LINKS_PLUGIN = '''from urllib.parse import urlparse

from botkit.config import Incoming


class Plugin:
    def on_text(self, message: Incoming) -> str | None:
        url = urlparse(message.text.strip())
        host = (url.hostname or "").lower()
        domains = ("tiktok.com", "youtube.com", "youtu.be")
        known = any(host == domain or host.endswith("." + domain) for domain in domains)
        if url.scheme == "https" and known:
            return ("Демо: ссылка распознана. Загрузка видео, распознавание речи "
                    "и анализ здесь не выполняются. Подключите обработчик в plugin.py.")
        return "Пришлите ссылку TikTok или YouTube. Это демонстрационный шаблон."
'''


def create_bot(name: str, destination: Path, template: str = "echo") -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name):
        raise ScaffoldError("Bot name must use lowercase Latin letters, digits or underscore")
    if template not in {"echo", "tt-links"}:
        raise ScaffoldError("Unknown template")
    target = Path(destination) / name
    if target.exists():
        raise ScaffoldError(f"Target already exists: {target}")
    target.mkdir(parents=True)
    start = (
        "Привет! Пришлите текст."
        if template == "echo"
        else "Привет! Пришлите ссылку TikTok или YouTube. Это демо без обработки видео."
    )
    lines = [
        "[bot]",
        f"name = {json.dumps(name, ensure_ascii=False)}",
        f"start_message = {json.dumps(start, ensure_ascii=False)}",
        'fallback_message = "Не удалось обработать сообщение."',
        'plugin = "plugin.py"',
        "",
        "[telegram]",
        'token_env = "BOT_TOKEN"',
        "poll_timeout = 25",
        "",
    ]
    (target / "bot.toml").write_text("\n".join(lines), encoding="utf-8")
    (target / "plugin.py").write_text(
        ECHO_PLUGIN if template == "echo" else TT_LINKS_PLUGIN, encoding="utf-8"
    )
    (target / ".env.example").write_text("BOT_TOKEN=put_your_own_token_here\n", encoding="utf-8")
    (target / ".gitignore").write_text(".env\n__pycache__/\n*.offset\n", encoding="utf-8")
    (target / "README.md").write_text(
        "# " + name + "\n\n"
        "Для запуска нужен установленный BotKit. Используйте Python из среды, куда он установлен; "
        "одной этой папки на другом компьютере недостаточно.\n\n"
        "1. Проверьте ответы в `python -m botkit demo --config bot.toml`.\n"
        "2. Настройте `bot.toml`; для своей логики измените `Plugin.on_text` в `plugin.py`.\n"
        "3. Для Telegram создайте бота у BotFather, скопируйте `.env.example` в `.env`, "
        "замените заглушку своим токеном и запустите `python -m botkit run --config bot.toml`.\n"
        "Не публикуйте `.env` и не вставляйте токен в запрос ИИ. "
        "Пользовательский `plugin.py` выполняется и в деморежиме: он может обращаться к сети и файлам.\n",
        encoding="utf-8",
    )
    return target
