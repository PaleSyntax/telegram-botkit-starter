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

TASK_PLUGIN = '''from pathlib import Path
from botkit.tasks import TaskPlugin


class Plugin(TaskPlugin):
    def __init__(self):
        super().__init__(Path(__file__).parent / "data" / "jobs.sqlite3")
'''

TASK_HANDLER = '''from botkit.config import Incoming


class Plugin:
    def on_text(self, message: Incoming) -> str:
        # Example business logic: one line becomes one checklist item.
        # Replace this method with your own integration or processing.
        items = [line.strip().lstrip("-* ") for line in message.text.splitlines() if line.strip().lstrip("-* ")]
        if not items:
            return "Список пуст. Напишите по одному пункту на строку."
        if len(items) > 30:
            return "В примере поддерживается до 30 пунктов."
        result = "Чек-лист:\\n" + "\\n".join(f"☐ {item}" for item in items)
        return result if len(result) <= 4096 else "Список слишком длинный. Разделите его на несколько задач."
'''


def create_bot(name: str, destination: Path, template: str = "echo") -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name):
        raise ScaffoldError("Bot name must use lowercase Latin letters, digits or underscore")
    if template not in {"echo", "tasks"}:
        raise ScaffoldError("Unknown template")
    target = Path(destination) / name
    if target.exists():
        raise ScaffoldError(f"Target already exists: {target}")
    target.mkdir(parents=True)
    start = (
        "Привет! Пришлите текст."
        if template == "echo"
        else "Пришлите пункты по одному на строку — обработчик соберёт чек-лист. Команды: /help."
    )
    lines = [
        "[bot]",
        f"name = {json.dumps(name, ensure_ascii=False)}",
        f"start_message = {json.dumps(start, ensure_ascii=False)}",
        'fallback_message = "Не удалось обработать сообщение."',
        'plugin = "plugin.py"',
        'allowed_users = []',
        "",
        "[telegram]",
        'token_env = "BOT_TOKEN"',
        "poll_timeout = 25",
        "",
    ]
    (target / "bot.toml").write_text("\n".join(lines), encoding="utf-8")
    (target / "plugin.py").write_text(
        ECHO_PLUGIN if template == "echo" else TASK_PLUGIN, encoding="utf-8"
    )
    if template == "tasks":
        (target / "task.py").write_text(TASK_HANDLER, encoding="utf-8")
    (target / ".env.example").write_text("BOT_TOKEN=put_your_own_token_here\n", encoding="utf-8")
    (target / ".gitignore").write_text(".env\n__pycache__/\ndata/\n*.offset\n", encoding="utf-8")
    (target / "README.md").write_text(
        "# " + name + "\n\n"
        "Для запуска нужен установленный BotKit. Используйте Python из среды, куда он установлен; "
        "одной этой папки на другом компьютере недостаточно.\n\n"
        "1. Проверьте ответы в `python -m botkit demo --config bot.toml`.\n"
        "2. Настройте `bot.toml`; свою логику задайте в обработчике выбранного шаблона.\n"
        "3. Для Telegram создайте бота у BotFather, скопируйте `.env.example` в `.env`, "
        "замените заглушку своим токеном и запустите `python -m botkit run --config bot.toml`.\n"
        "Не публикуйте `.env` и не вставляйте токен в запрос ИИ. "
        "Пользовательский `plugin.py` выполняется и в деморежиме: он может обращаться к сети и файлам.\n",
        encoding="utf-8",
    )
    if template == "tasks":
        with (target / "README.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "\nЛогику задачи меняйте в `task.py`. Запустите worker во втором терминале: "
                "`python -m botkit worker --config bot.toml`. Для одной задачи добавьте `--once`. "
                "Проверяйте результат командой `/status <номер>` в боте. "
                "Задания и результаты находятся в `data/jobs.sqlite3`; храните эту папку приватно.\n"
            )
    return target
