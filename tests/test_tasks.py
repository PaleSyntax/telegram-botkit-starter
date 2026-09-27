from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from botkit.cli import main
from botkit.config import Incoming, load_plugin, load_settings
from botkit.core import Bot, Runner
from botkit.jobs import JobStore
from botkit.scaffold import create_bot
from botkit.state import CursorStore
from botkit.tasks import TaskPlugin, work_once
from botkit.transport import FakeTransport


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = create_bot("sample", Path(self.temp.name), "tasks")
        self.config = self.folder / "bot.toml"
        self.settings = load_settings(self.config)
        self.plugin = load_plugin(self.config, self.settings)
        self.bot = Bot(self.settings, self.plugin)
        self.store = self.plugin.store
        self.handler = load_plugin(self.config, replace(self.settings, plugin_file="task.py"))

    def enqueue(self, text="First\nSecond", update_id=1):
        reply = self.bot.reply(Incoming(7, 8, text, update_id))
        return reply.split()[1]

    def test_full_lifecycle_and_result_survives_restart(self):
        job_id = self.enqueue()
        job = work_once(self.store, self.handler)
        self.assertEqual(job["state"], "done")
        restarted = TaskPlugin(self.store.path)
        answer = restarted.on_text(Incoming(7, 8, f"/status {job_id}"))
        self.assertEqual(answer, "Чек-лист:\n☐ First\n☐ Second")
        self.assertIsNone(work_once(self.store, self.handler))

    def test_replayed_update_deduplicated_but_new_message_is_new_job(self):
        first = self.enqueue()
        self.assertEqual(first, self.enqueue())
        self.assertNotEqual(first, self.enqueue(update_id=2))

    def test_other_owner_cannot_read_retry_or_cancel(self):
        job_id = self.enqueue()
        for command in ("/status", "/retry", "/cancel"):
            for message in (Incoming(9, 8, f"{command} {job_id}"), Incoming(7, 9, f"{command} {job_id}")):
                self.assertEqual(self.bot.reply(message), "Задача не найдена.")

    def test_group_and_anonymous_messages_do_not_enqueue(self):
        for message in (Incoming(-7, 8, "text"), Incoming(7, None, "text")):
            self.assertIn("личный чат", self.bot.reply(message))
        self.assertIsNone(self.store.claim())

    def test_cancelled_job_not_processed(self):
        job_id = self.enqueue()
        self.assertIn("отменена", self.bot.reply(Incoming(7, 8, f"/cancel {job_id}")))
        self.assertIsNone(self.store.claim())

    def test_failure_sanitized_and_explicit_retry_works(self):
        class Failing:
            def on_text(self, message):
                raise RuntimeError("private credential sample")
        job_id = self.enqueue()
        job = work_once(self.store, Failing())
        self.assertEqual(job["state"], "failed")
        self.assertNotIn("private credential", json.dumps(job))
        self.assertTrue(self.store.retry(job_id, "7:8"))
        self.assertEqual(work_once(self.store, self.handler)["state"], "done")

    def test_oversized_reply_fails_without_storing_it(self):
        class Huge:
            def on_text(self, message):
                return "x" * 4097
        self.enqueue()
        job = work_once(self.store, Huge())
        self.assertEqual(job["state"], "failed")
        self.assertIsNone(job["result"])

    def test_queue_limit_and_duplicate_at_limit(self):
        first = self.enqueue()
        for value in range(2, 21):
            self.enqueue(update_id=value)
        self.assertEqual(first, self.enqueue())
        self.assertIn("20 задач", self.bot.reply(Incoming(7, 8, "extra", 21)))

    def test_retry_cannot_bypass_queue_limit(self):
        first = self.enqueue()
        self.store.claim()
        self.store.finish(first, None, "sample failure")
        for value in range(2, 22):
            self.enqueue(update_id=value)
        self.assertFalse(self.store.retry(first, "7:8"))

    def test_concurrent_workers_do_not_claim_same_job(self):
        job_id = self.enqueue()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda _: JobStore(self.store.path).claim(), range(4)))
        self.assertEqual([job["id"] for job in claimed if job], [job_id])

    def test_restart_does_not_automatically_requeue_running_job(self):
        self.enqueue()
        self.store.claim()
        restarted = JobStore(self.store.path)
        self.assertIsNone(restarted.claim())
        self.assertEqual(restarted.recover(), 1)
        self.assertIsNotNone(restarted.claim())

    def test_allowlist_blocks_before_plugin_or_start(self):
        restricted = Bot(replace(self.settings, allowed_users=(8,)), self.plugin)
        for text in ("task", "/start"):
            self.assertIn("ограничен", restricted.reply(Incoming(7, 9, text)))
        self.assertIsNone(self.store.claim())

    def test_polling_restart_does_not_resend_completed_update(self):
        state = CursorStore(self.folder / "data" / "polling.sqlite3")
        update = {"update_id": 5, "message": {"chat": {"id": 7}, "from": {"id": 8}, "text": "task"}}
        first = FakeTransport([update])
        Runner(self.bot, first, state=state).step()
        second = FakeTransport([update])
        Runner(self.bot, second, state=CursorStore(state.path)).step()
        self.assertEqual(len(first.sent), 1)
        self.assertEqual(second.sent, [])

    def test_failed_send_preserves_cursor_and_task_is_not_duplicated(self):
        state = CursorStore(self.folder / "data" / "polling.sqlite3")
        update = {"update_id": 5, "message": {"chat": {"id": 7}, "from": {"id": 8}, "text": "task"}}
        first = FakeTransport([update])
        with patch.object(first, "send", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                Runner(self.bot, first, state=state).step()
        self.assertIsNone(state.load())
        Runner(self.bot, FakeTransport([update]), state=state).step()
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(self.store.claim())

    def test_worker_cli_once(self):
        job_id = self.enqueue()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["worker", "--config", str(self.config), "--once"]), 0)
        self.assertEqual(self.store.get(job_id, "7:8")["state"], "done")

    def test_example_is_offline_and_finishes(self):
        output = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            with redirect_stdout(output):
                self.assertEqual(main(["example"]), 0)
        self.assertIn("☐ Проверить результат", output.getvalue())

    def test_example_emits_utf8_even_with_ascii_terminal_default(self):
        environment = {**os.environ, "PYTHONIOENCODING": "ascii"}
        completed = subprocess.run([sys.executable, "-m", "botkit", "example"],
                                   env=environment, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
        self.assertIn("☐ Проверить результат", completed.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
