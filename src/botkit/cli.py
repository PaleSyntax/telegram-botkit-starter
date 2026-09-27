"""botkit new, demo and run."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time

from botkit.config import ConfigError, Incoming, load_plugin, load_settings, load_token
from botkit.core import Bot, Runner
from botkit.scaffold import ScaffoldError, create_bot
from botkit.transport import BotApiError, FakeTransport, TelegramTransport
from botkit.jobs import JobStore
from botkit.state import CursorStore
from botkit.tasks import work_once


def _bot(config_path: Path) -> Bot:
    settings = load_settings(config_path)
    return Bot(settings, load_plugin(config_path, settings))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="botkit", description="Small Telegram bot starter")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("example", help="Run the entire task lifecycle in a temporary folder without Telegram")
    new = sub.add_parser("new", help="Create a bot folder")
    new.add_argument("name")
    new.add_argument("--dest", type=Path, default=Path.cwd())
    new.add_argument("--template", choices=("echo", "tasks"), default="tasks")
    demo = sub.add_parser("demo", help="Use a local fake transport; custom plugins may access the network")
    demo.add_argument("--config", type=Path, required=True)
    demo.add_argument("--text", action="append", default=[])
    run = sub.add_parser("run", help="Use Telegram Bot API long polling")
    run.add_argument("--config", type=Path, required=True)
    worker = sub.add_parser("worker", help="Process generic tasks using the local task.py handler")
    worker.add_argument("--config", type=Path, required=True)
    worker.add_argument("--once", action="store_true", help="Process at most one job and exit")
    recover = sub.add_parser("recover", help="Requeue interrupted jobs AFTER stopping all workers")
    recover.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows redirected output may use a legacy code page without Cyrillic or symbols.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        if args.command == "example":
            with tempfile.TemporaryDirectory(prefix="botkit-example-") as temp:
                folder = create_bot("example", Path(temp), "tasks")
                config = folder / "bot.toml"
                bot = _bot(config)
                fake = FakeTransport([{"update_id": 1, "message": {
                    "chat": {"id": 1}, "from": {"id": 1},
                    "text": "Сформулировать задачу\nПроверить результат\nЗаписать выводы"}}])
                Runner(bot, fake).step()
                print(fake.sent[0][1])
                handler = load_plugin(config, replace(bot.settings, plugin_file="task.py"))
                job = work_once(JobStore(folder / "data" / "jobs.sqlite3"), handler)
                if job is None or job["state"] != "done":
                    return 1
                print(bot.reply(Incoming(1, 1, f"/status {job['id']}")))
            return 0
        if args.command == "new":
            print(create_bot(args.name, args.dest, args.template))
            return 0
        if args.command in {"worker", "recover"}:
            settings = load_settings(args.config)
            store = JobStore(args.config.parent / "data" / "jobs.sqlite3")
            if args.command == "recover":
                print(f"Recovered jobs: {store.recover()}")
                return 0
            handler = load_plugin(args.config, replace(settings, plugin_file="task.py"))
            while True:
                job = work_once(store, handler)
                if job:
                    print(f"{job['id']}: {job['state']}", flush=True)
                if args.once:
                    return 1 if job and job["state"] == "failed" else 0
                if job is None:
                    time.sleep(1)
        bot = _bot(args.config)
        if args.command == "demo":
            texts = ["/start", *(args.text or ["Привет!"])]
            fake = FakeTransport([
                {"update_id": time.time_ns() + index, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": value}}
                for index, value in enumerate(texts, 1)
            ])
            Runner(bot, fake).step()
            for incoming, (_, answer) in zip(texts, fake.sent):
                print(f"> {incoming}\n{answer}")
            return 0
        token = load_token(args.config, bot.settings.token_env)
        runner = Runner(bot, TelegramTransport(token), state=CursorStore(args.config.parent / "data" / "polling.sqlite3"))
        print(f"Running {bot.settings.name}; stop with Ctrl+C.")
        while True:
            try:
                runner.step()
            except BotApiError:
                print("Telegram API unavailable; retrying shortly.", file=sys.stderr)
                time.sleep(3)
    except (ConfigError, ScaffoldError, ValueError) as exc:
        print(f"botkit: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
