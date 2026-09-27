"""Generic queued text tasks; application logic lives in the generated task.py."""

from __future__ import annotations

import json
from pathlib import Path

from botkit.config import Incoming, TextPlugin
from botkit.core import validate_reply
from botkit.jobs import JobStore


def work_once(store: JobStore, handler: TextPlugin) -> dict | None:
    job = store.claim()
    if job is None:
        return None
    try:
        payload = json.loads(job["source"])
        answer = validate_reply(handler.on_text(Incoming(**payload)))
        store.finish(job["id"], {"text": answer})
    except Exception:
        # Handler exceptions can contain credentials. Do not retain or send them.
        store.finish(job["id"], None, "Обработчик завершился с ошибкой. Доступен /retry.")
    return store.get(job["id"], job["owner"])


class TaskPlugin:
    def __init__(self, path: Path):
        self.store = JobStore(path)

    def on_text(self, message: Incoming) -> str:
        if message.chat_id <= 0 or message.user_id is None:
            return "Используйте личный чат с ботом."
        owner = f"{message.chat_id}:{message.user_id}"
        parts = message.text.strip().split()
        command = parts[0].split("@", 1)[0] if parts else ""
        if command == "/help":
            return "Отправьте текст задачи. /status <номер> — результат; /retry <номер> — повтор после ошибки; /cancel <номер> — отмена в очереди."
        if command in {"/status", "/retry", "/cancel"}:
            if len(parts) != 2:
                return f"Используйте {command} <номер задачи>."
            job = self.store.get(parts[1], owner)
            if job is None:
                return "Задача не найдена."
            if command == "/retry":
                return "Задача снова в очереди." if self.store.retry(job["id"], owner) else "Повтор доступен только после ошибки и при наличии места в очереди."
            if command == "/cancel":
                return "Задача отменена." if self.store.cancel(job["id"], owner) else "Отменить можно только задачу в очереди."
            if job["state"] == "done":
                return json.loads(job["result"])["text"]
            labels = {"queued": "в очереди", "running": "обрабатывается", "failed": "ошибка", "cancelled": "отменена"}
            return f"Задача {job['id']}: {labels[job['state']]}.\n{job['error'] or ''}".strip()
        if command.startswith("/") or not message.text.strip():
            return "Отправьте текст задачи или /help."
        payload = json.dumps({"chat_id": message.chat_id, "user_id": message.user_id,
                              "text": message.text, "update_id": message.update_id}, ensure_ascii=False)
        try:
            job = self.store.enqueue(owner, payload)
        except ValueError:
            return "В очереди уже 20 задач. Дождитесь обработки."
        return f"Задача {job['id']} сохранена.\n/status {job['id']}"
