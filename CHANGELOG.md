# Changes

## 0.2.0

- Generic `tasks` template with a replaceable `task.py` handler and checklist example.
- SQLite queue, per-owner results, cancellation, explicit retries and a 20-job active limit.
- Atomic worker claims and explicit recovery of interrupted jobs.
- Persistent Telegram polling cursor and deduplication of replayed task submissions.
- Optional user allowlist, private-chat task commands and sanitized handler failures.
- Full offline `example` command, UTF-8 CLI output and installation documentation.

The CLI now creates `tasks` by default; pass `--template echo` for the synchronous example.
Existing generated folders are not modified automatically. Create a new folder to try the
new template. Run one poller per bot folder; run the task worker in a separate terminal.
User plugins are trusted local code. External side effects need their own idempotency and
timeouts. Live Telegram and production load have not been verified.
