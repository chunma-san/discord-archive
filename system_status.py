import asyncio
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def setup_system_status(
    client,
    db_path,
    send_log,
):
    status_task_started = False

    project_dir = Path(db_path).resolve().parent.parent
    backup_dir = project_dir / "backups"
    attachments_dir = project_dir / "data" / "attachments"


    def human_size(size):
        size = float(size)

        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if size < 1024 or unit == "TiB":
                return f"{size:.2f} {unit}"

            size /= 1024


    def directory_size(path):
        if not path.exists():
            return 0

        total = 0

        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                pass

        return total


    def database_status():
        db_file = Path(db_path)

        with sqlite3.connect(db_file, timeout=30.0) as db:
            integrity = db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            tables = [
                "messages",
                "message_edits",
                "attachments",
                "reactions",
                "member_events",
                "presence_events",
                "voice_events",
                "voice_sessions",
                "server_events",
                "audit_events",
            ]

            counts = {}

            for table in tables:
                try:
                    counts[table] = db.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                except sqlite3.Error:
                    counts[table] = "N/A"

        return (
            integrity,
            db_file.stat().st_size if db_file.exists() else 0,
            counts,
        )


    async def send_status():
        try:
            integrity, db_size, counts = await asyncio.to_thread(
                database_status
            )

            count_text = "\n".join(
                f"**{name}:** `{value}`"
                for name, value in counts.items()
            )

            await send_log(
                "database-status",
                "🗄️ Database Status",
                (
                    f"**Integrity:** `{integrity}`\n"
                    f"**Database size:** `{human_size(db_size)}`\n\n"
                    f"{count_text}"
                ),
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Database Status Error",
                f"`{type(e).__name__}: {e}`",
            )

        try:
            backup_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            backups = sorted(
                backup_dir.glob("big_brain_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if backups:
                latest = backups[0]

                modified = datetime.fromtimestamp(
                    latest.stat().st_mtime,
                    timezone.utc,
                ).isoformat()

                backup_text = (
                    f"**Latest:** `{latest.name}`\n"
                    f"**Size:** "
                    f"`{human_size(latest.stat().st_size)}`\n"
                    f"**Created:** `{modified}`\n"
                    f"**DB backups:** `{len(backups)}`"
                )
            else:
                backup_text = (
                    "**Latest:** `None`\n"
                    "**DB backups:** `0`"
                )

            await send_log(
                "backup-status",
                "💾 Backup Status",
                backup_text,
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Backup Status Error",
                f"`{type(e).__name__}: {e}`",
            )

        try:
            usage = shutil.disk_usage(project_dir)

            attachment_size = await asyncio.to_thread(
                directory_size,
                attachments_dir,
            )

            await send_log(
                "storage-status",
                "💽 Storage Status",
                (
                    f"**Disk total:** "
                    f"`{human_size(usage.total)}`\n"
                    f"**Disk used:** "
                    f"`{human_size(usage.used)}`\n"
                    f"**Disk free:** "
                    f"`{human_size(usage.free)}`\n"
                    f"**Attachments:** "
                    f"`{human_size(attachment_size)}`"
                ),
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Storage Status Error",
                f"`{type(e).__name__}: {e}`",
            )


    async def status_worker():
        await client.wait_until_ready()

        while not client.is_closed():
            await send_status()
            await asyncio.sleep(6 * 60 * 60)


    @client.listen("on_ready")
    async def system_status_on_ready():
        nonlocal status_task_started

        if status_task_started:
            return

        status_task_started = True

        client.loop.create_task(
            status_worker()
        )
