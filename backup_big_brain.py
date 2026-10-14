from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import shutil
import tarfile


BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB = DATA / "big_brain.db"
ATTACHMENTS = DATA / "attachments"
BACKUPS = BASE / "backups"

KEEP = 14


def timestamp():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d_%H-%M-%S")


def newest_mtime(path):
    if not path.exists():
        return 0

    newest = path.stat().st_mtime

    for item in path.rglob("*"):
        try:
            newest = max(
                newest,
                item.stat().st_mtime,
            )
        except OSError:
            pass

    return newest


def cleanup(pattern):
    files = sorted(
        BACKUPS.glob(pattern),
        key=lambda p: p.name,
        reverse=True,
    )

    for old in files[KEEP:]:
        old.unlink(missing_ok=True)


def main():
    BACKUPS.mkdir(
        parents=True,
        exist_ok=True,
    )

    BACKUPS.chmod(0o700)

    if not DB.exists():
        raise SystemExit(
            f"Database not found: {DB}"
        )

    stamp = timestamp()

    # =====================================================
    # SQLITE CONSISTENT BACKUP
    # =====================================================

    db_backup = (
        BACKUPS
        / f"big_brain_{stamp}.db"
    )

    source = sqlite3.connect(DB, timeout=30.0)
    destination = sqlite3.connect(
        db_backup
    )

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    db_backup.chmod(0o600)

    print(
        f"Database backup: {db_backup}"
    )

    # =====================================================
    # ENV BACKUP
    # =====================================================

    env = BASE / ".env"

    if env.exists():
        env_backup = (
            BACKUPS
            / f"env_{stamp}.backup"
        )

        shutil.copy2(
            env,
            env_backup,
        )

        env_backup.chmod(0o600)

        print(
            f"Environment backup: {env_backup}"
        )

    # =====================================================
    # ATTACHMENTS BACKUP
    # Only create a new archive when attachments changed.
    # =====================================================

    if ATTACHMENTS.exists():
        previous = sorted(
            BACKUPS.glob(
                "attachments_*.tar.gz"
            ),
            key=lambda p: p.name,
            reverse=True,
        )

        latest_archive_time = (
            previous[0].stat().st_mtime
            if previous
            else 0
        )

        attachment_mtime = newest_mtime(
            ATTACHMENTS
        )

        if attachment_mtime > latest_archive_time:
            attachment_backup = (
                BACKUPS
                / f"attachments_{stamp}.tar.gz"
            )

            with tarfile.open(
                attachment_backup,
                "w:gz",
            ) as tar:
                tar.add(
                    ATTACHMENTS,
                    arcname="attachments",
                )

            attachment_backup.chmod(0o600)

            print(
                "Attachments backup: "
                f"{attachment_backup}"
            )

        else:
            print(
                "Attachments unchanged; "
                "archive skipped."
            )

    else:
        print(
            "Attachments directory not found; "
            "archive skipped."
        )

    # =====================================================
    # RETENTION
    # =====================================================

    cleanup("big_brain_*.db")
    cleanup("env_*.backup")
    cleanup("attachments_*.tar.gz")

    print("Backup completed successfully.")


if __name__ == "__main__":
    main()
