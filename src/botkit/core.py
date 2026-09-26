"""Text dispatch and a small update loop, shared by offline and Telegram transports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from botkit.config import BotSettings, Incoming, TextPlugin


class Transport(Protocol):
    def receive(self, offset: int | None, timeout: int) -> list[dict]: ...
    def send(self, chat_id: int, text: str) -> None: ...


def _reply_text(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Plugin reply must be a nonempty string")
    if len(value) > 4096:
        raise ValueError("Plugin reply exceeds Telegram's 4096 character limit")
    return value


@dataclass
class Bot:
    settings: BotSettings
    plugin: TextPlugin

    def reply(self, message: Incoming) -> str:
        command = message.text.strip().split(maxsplit=1)[0].split("@", 1)[0] if message.text.strip() else ""
        if command == "/start":
            return _reply_text(self.settings.start_message)
        try:
            answer = self.plugin.on_text(message)
            return _reply_text(answer if answer is not None else self.settings.fallback_message)
        except Exception:
            # A faulty plugin or oversized reply must not stop the polling loop.
            return _reply_text(self.settings.fallback_message)


def incoming_from_update(update: Mapping) -> Incoming | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    text = message.get("text")
    if not isinstance(chat, dict) or not isinstance(text, str):
        return None
    chat_id = chat.get("id")
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        return None
    user_id = sender.get("id") if isinstance(sender, dict) else None
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        user_id = None
    return Incoming(chat_id=chat_id, user_id=user_id, text=text)


@dataclass
class Runner:
    bot: Bot
    transport: Transport
    offset: int | None = None

    def step(self) -> int | None:
        """Process one poll. A failed send leaves the update unconfirmed for retry."""
        updates = self.transport.receive(self.offset, self.bot.settings.poll_timeout)
        for update in sorted(updates, key=lambda item: item.get("update_id", -1)):
            update_id = update.get("update_id")
            if isinstance(update_id, bool) or not isinstance(update_id, int):
                continue
            if self.offset is not None and update_id < self.offset:
                continue
            message = incoming_from_update(update)
            if message is not None:
                self.transport.send(message.chat_id, self.bot.reply(message))
            self.offset = update_id + 1
        return self.offset
