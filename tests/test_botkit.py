from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

import botkit.cli as cli
from botkit.cli import main
from botkit.config import ConfigError, Incoming, load_plugin, load_settings, load_token
from botkit.core import Bot, Runner
from botkit.scaffold import ScaffoldError, create_bot
from botkit.transport import BotApiError, FakeTransport, TelegramTransport


class GeneratedBotTests(unittest.TestCase):
    def test_echo_bot_runs_from_generated_folder_and_config_changes_reply(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            config = folder / "bot.toml"
            config.write_text(config.read_text(encoding="utf-8").replace("Привет! Пришлите текст.", "Мой текст."), encoding="utf-8")
            settings = load_settings(config)
            bot = Bot(settings, load_plugin(config, settings))
            fake = FakeTransport([
                {"update_id": 10, "message": {"chat": {"id": 7}, "from": {"id": 8}, "text": "/start"}},
                {"update_id": 11, "message": {"chat": {"id": 7}, "from": {"id": 8}, "text": "test"}},
                {"update_id": 12, "message": {"chat": {"id": 7}, "photo": []}},
            ])
            runner = Runner(bot, fake)
            self.assertEqual(runner.step(), 13)
            self.assertEqual(fake.sent, [(7, "Мой текст."), (7, "Вы написали: test")])
            self.assertEqual(runner.step(), 13)
            self.assertEqual(len(fake.sent), 2)

    def test_tt_links_is_an_explicit_stub(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("links", Path(temp), template="tt-links")
            config = folder / "bot.toml"
            settings = load_settings(config)
            bot = Bot(settings, load_plugin(config, settings))
            reply = bot.reply(Incoming(1, 1, "https://youtu.be/example"))
            self.assertIn("не выполняются", reply)
            self.assertIn("plugin.py", reply)
            self.assertIn("Пришлите ссылку", bot.reply(Incoming(1, 1, "https://youtube.com.evil.example/watch")))

    def test_generator_never_overwrites_existing_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            marker = folder / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(ScaffoldError):
                create_bot("mybot", Path(temp))
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_config_rejects_plugin_escape_and_token_is_never_in_error(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            config = folder / "bot.toml"
            config.write_text(config.read_text(encoding="utf-8").replace('plugin = "plugin.py"', 'plugin = "../other.py"'), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(config)
            config.write_text(config.read_text(encoding="utf-8").replace('plugin = "../other.py"', 'plugin = "plugin.py"'), encoding="utf-8")
            with patch.dict(os.environ, {"BOT_TOKEN": ""}):
                with self.assertRaises(ConfigError) as captured:
                    load_token(config, "BOT_TOKEN")
            self.assertNotIn("put_your_own_token_here", str(captured.exception))

    def test_failed_send_keeps_update_for_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            config = folder / "bot.toml"
            settings = load_settings(config)

            class FailingTransport(FakeTransport):
                def send(self, chat_id, text):
                    raise RuntimeError("synthetic failure")

            fake = FailingTransport([
                {"update_id": 3, "message": {"chat": {"id": 7}, "text": "hello"}}
            ])
            runner = Runner(Bot(settings, load_plugin(config, settings)), fake)
            with self.assertRaises(RuntimeError):
                runner.step()
            self.assertIsNone(runner.offset)

    def test_cli_demo_uses_no_network(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            self.assertEqual(main(["demo", "--config", str(folder / "bot.toml"), "--text", "hello"]), 0)

    def test_cli_run_reads_local_env_and_uses_fake_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            (folder / ".env").write_text("BOT_TOKEN=synthetic-token\n", encoding="utf-8")

            class StopAfterOnePoll(FakeTransport):
                polls = 0
                def receive(self, offset, timeout):
                    self.polls += 1
                    if self.polls > 1:
                        raise KeyboardInterrupt
                    return super().receive(offset, timeout)

            fake = StopAfterOnePoll([
                {"update_id": 1, "message": {"chat": {"id": 7}, "text": "hello"}}
            ])
            seen_tokens = []
            def fake_telegram(token):
                seen_tokens.append(token)
                return fake

            with patch.dict(os.environ, {"BOT_TOKEN": ""}):
                with patch.object(cli, "TelegramTransport", side_effect=fake_telegram):
                    self.assertEqual(main(["run", "--config", str(folder / "bot.toml")]), 0)
            self.assertEqual(seen_tokens, ["synthetic-token"])
            self.assertEqual(fake.sent, [(7, "Вы написали: hello")])


class TelegramAdapterTests(unittest.TestCase):
    def test_poll_and_send_payloads_without_network(self):
        calls = []

        class Response:
            def __init__(self, result):
                self.data = json.dumps({"ok": True, "result": result}).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, size):
                return self.data

        def opener(req, timeout):
            calls.append((req.full_url.rsplit("/", 1)[-1], json.loads(req.data), timeout))
            return Response([] if calls[-1][0] == "getUpdates" else {"message_id": 1})

        transport = TelegramTransport("synthetic-token", opener=opener)
        self.assertEqual(transport.receive(12, 25), [])
        transport.send(9, "hello")
        self.assertEqual(calls[0], ("getUpdates", {"timeout": 25, "allowed_updates": ["message"], "offset": 12}, 35))
        self.assertEqual(calls[1], ("sendMessage", {"chat_id": 9, "text": "hello"}, 15))

    def test_network_exception_does_not_expose_token(self):
        def failed(req, timeout):
            raise error.URLError(req.full_url)

        transport = TelegramTransport("synthetic-token", opener=failed)
        with self.assertRaises(BotApiError) as captured:
            transport.receive(None, 25)
        self.assertNotIn("synthetic-token", str(captured.exception))
        with self.assertRaises(ValueError) as invalid:
            TelegramTransport("synthetic-token/unsafe")
        self.assertNotIn("synthetic-token", str(invalid.exception))


if __name__ == "__main__":
    unittest.main()
