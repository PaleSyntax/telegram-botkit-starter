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

    def test_tasks_template_enqueues_and_rejects_unknown_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("tasks", Path(temp), template="tasks")
            config = folder / "bot.toml"
            settings = load_settings(config)
            bot = Bot(settings, load_plugin(config, settings))
            reply = bot.reply(Incoming(1, 1, "Prepare a checklist"))
            self.assertIn("сохранена", reply)
            self.assertIn("/status", reply)
            self.assertIn("/help", bot.reply(Incoming(1, 1, "/unknown")))

    def test_long_echo_reply_uses_fallback_and_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            config = folder / "bot.toml"
            settings = load_settings(config)
            fake = FakeTransport([
                {"update_id": 1, "message": {"chat": {"id": 7}, "text": "x" * 4096}},
                {"update_id": 2, "message": {"chat": {"id": 7}, "text": "ok"}},
            ])
            runner = Runner(Bot(settings, load_plugin(config, settings)), fake)
            self.assertEqual(runner.step(), 3)
            self.assertEqual(fake.sent, [
                (7, settings.fallback_message),
                (7, "Вы написали: ok"),
            ])

    def test_handler_exception_uses_fallback_and_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("sample", Path(temp))
            config = folder / "bot.toml"
            settings = load_settings(config)
            fake = FakeTransport([
                {"update_id": 1, "message": {"chat": {"id": 7}, "text": "fail"}},
                {"update_id": 2, "message": {"chat": {"id": 7}, "text": "ok"}},
            ])
            class Handler:
                def on_text(self, message):
                    if message.text == "fail":
                        raise ValueError("private exception details")
                    return "ok"
            runner = Runner(Bot(settings, Handler()), fake)
            self.assertEqual(runner.step(), 3)
            self.assertEqual(fake.sent[0], (7, settings.fallback_message))
            self.assertEqual("ok", fake.sent[1][1])

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

    def test_start_and_fallback_message_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            config = folder / "bot.toml"
            original = config.read_text(encoding="utf-8")
            for key in ("start_message", "fallback_message"):
                original_line = next(line for line in original.splitlines() if line.startswith(key + " = "))
                for length in (4096, 4097):
                    with self.subTest(key=key, length=length):
                        config.write_text(
                            original.replace(original_line, f'{key} = "{"x" * length}"'),
                            encoding="utf-8",
                        )
                        if length == 4096:
                            self.assertEqual(len(getattr(load_settings(config), key)), 4096)
                        else:
                            with self.assertRaises(ConfigError):
                                load_settings(config)

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
        self.assertEqual(calls[0], ("getUpdates", {"timeout": 25, "limit": 10, "allowed_updates": ["message"], "offset": 12}, 35))
        self.assertEqual(calls[1], ("sendMessage", {"chat_id": 9, "text": "hello"}, 15))

    def test_large_pending_queue_is_polled_in_bounded_batches(self):
        updates = [
            {"update_id": index, "message": {"chat": {"id": 7}, "text": "😀" * 3000}}
            for index in range(1, 101)
        ]
        self.assertGreater(len(json.dumps({"ok": True, "result": updates}, ensure_ascii=False).encode("utf-8")), 1_000_000)
        polls = []
        sent = []

        class Response:
            def __init__(self, result):
                self.data = json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, size):
                return self.data[:size]

        def opener(req, timeout):
            del timeout
            payload = json.loads(req.data)
            if req.full_url.endswith("/getUpdates"):
                polls.append(payload)
                offset = payload.get("offset", 1)
                batch = [item for item in updates if item["update_id"] >= offset][:payload["limit"]]
                return Response(batch)
            sent.append(payload)
            return Response({"message_id": len(sent)})

        with tempfile.TemporaryDirectory() as temp:
            folder = create_bot("mybot", Path(temp))
            config = folder / "bot.toml"
            settings = load_settings(config)
            runner = Runner(Bot(settings, load_plugin(config, settings)), TelegramTransport("synthetic-token", opener=opener))
            for _ in range(10):
                runner.step()
        self.assertEqual(runner.offset, 101)
        self.assertEqual(len(sent), 100)
        self.assertEqual(len(polls), 10)
        self.assertTrue(all(poll["limit"] == 10 for poll in polls))

    def test_transport_accepts_response_above_old_one_megabyte_cap(self):
        large_response = json.dumps({"ok": True, "result": [{"update_id": 1, "padding": "x" * 1_100_000}]}).encode("utf-8")

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, size):
                return large_response[:size]

        transport = TelegramTransport("synthetic-token", opener=lambda req, timeout: Response())
        self.assertEqual(transport.receive(None, 25)[0]["update_id"], 1)

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
