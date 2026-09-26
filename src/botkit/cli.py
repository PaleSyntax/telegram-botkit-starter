"""botkit new, demo and run."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from botkit.config import ConfigError, load_plugin, load_settings, load_token
from botkit.core import Bot, Runner
from botkit.scaffold import ScaffoldError, create_bot
from botkit.transport import BotApiError, FakeTransport, TelegramTransport


def _bot(config_path: Path) -> Bot:
    settings = load_settings(config_path)
    return Bot(settings, load_plugin(config_path, settings))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="botkit", description="Small Telegram bot starter")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="Create a bot folder")
    new.add_argument("name")
    new.add_argument("--dest", type=Path, default=Path.cwd())
    new.add_argument("--template", choices=("echo", "tt-links"), default="echo")
    demo = sub.add_parser("demo", help="Run without network or a Telegram token")
    demo.add_argument("--config", type=Path, required=True)
    demo.add_argument("--text", action="append", default=[])
    run = sub.add_parser("run", help="Use Telegram Bot API long polling")
    run.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "new":
            print(create_bot(args.name, args.dest, args.template))
            return 0
        bot = _bot(args.config)
        if args.command == "demo":
            texts = ["/start", *(args.text or ["Привет!"])]
            fake = FakeTransport([
                {"update_id": index, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": value}}
                for index, value in enumerate(texts, 1)
            ])
            Runner(bot, fake).step()
            for incoming, (_, answer) in zip(texts, fake.sent):
                print(f"> {incoming}\n{answer}")
            return 0
        token = load_token(args.config, bot.settings.token_env)
        runner = Runner(bot, TelegramTransport(token))
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
