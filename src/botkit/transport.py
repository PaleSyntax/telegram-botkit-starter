"""Offline fake and a minimal stdlib Telegram Bot API polling adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
import re
from typing import Callable
from urllib import request


class BotApiError(RuntimeError):
    """A sanitized Telegram API failure (never contains a bot token)."""


@dataclass
class FakeTransport:
    updates: list[dict] = field(default_factory=list)
    sent: list[tuple[int, str]] = field(default_factory=list)

    def receive(self, offset: int | None, timeout: int) -> list[dict]:
        del timeout
        return [item for item in self.updates if offset is None or item.get("update_id", -1) >= offset]

    def send(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class TelegramTransport:
    """Only plain text messages and long polling; no webhook or media support."""

    def __init__(self, token: str, opener: Callable = request.urlopen):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9:_-]+", token):
            raise ValueError("Bot token is missing or has invalid characters")
        self._url = f"https://api.telegram.org/bot{token}/"
        self._opener = opener

    def _call(self, method: str, payload: dict, timeout: int) -> object:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self._url + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(req, timeout=timeout) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise BotApiError(f"{method}: response is too large")
            result = json.loads(raw)
        except Exception:
            raise BotApiError(f"{method}: network or invalid response") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise BotApiError(f"{method}: Telegram returned an error")
        return result.get("result")

    def receive(self, offset: int | None, timeout: int) -> list[dict]:
        payload: dict = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload, timeout + 10)
        if not isinstance(result, list):
            raise BotApiError("getUpdates: invalid result")
        return result

    def send(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", {"chat_id": chat_id, "text": text}, 15)
