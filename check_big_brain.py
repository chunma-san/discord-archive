from pathlib import Path
import sqlite3


BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "big_brain.db"


def main():
    if not DB.exists():
        raise SystemExit(
            "ERROR: database missing"
        )

    con = sqlite3.connect(DB)

    try:
        integrity = con.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        print(
            "Integrity:",
            integrity,
        )

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

        print()

        for table in tables:
            try:
                count = con.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                print(
                    f"{table:20} {count}"
                )

            except Exception as e:
                print(
                    f"{table:20} ERROR: {e}"
                )

    finally:
        con.close()


if __name__ == "__main__":
    main()
