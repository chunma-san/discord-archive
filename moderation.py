from datetime import datetime, timezone
import json
import asyncio

import aiosqlite
from database import connect_db
import discord


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe(value):
    if value is None:
        return None

    try:
        return str(value)
    except Exception:
        return repr(value)


def safe_audit_target(entry):
    # Deleted / unavailable targets can legitimately have a null target_id.
    # discord.py 2.7.1 otherwise constructs Object(None) for channel/role events.
    if getattr(entry, "_target_id", None) is None:
        return None
    return entry.target


def setup_moderation(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    seen_audit_ids = set()


    async def save_server_event(
        event_type,
        target_id=None,
        actor_id=None,
        data=None,
    ):
        async with connect_db(db_path) as db:
            await db.execute(
                """
                INSERT INTO server_events (
                    guild_id,
                    event_type,
                    target_id,
                    actor_id,
                    data,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_guild_id,
                    event_type,
                    target_id,
                    actor_id,
                    json.dumps(
                        data or {},
                        ensure_ascii=False,
                        default=str,
                    ),
                    utc_now(),
                ),
            )

            await db.commit()


    async def find_recent_audit(
        guild,
        action,
        target_id,
    ):
        try:
            await asyncio.sleep(1)

            async for entry in guild.audit_logs(
                limit=8,
                action=action,
            ):
                target = safe_audit_target(entry)

                if (
                    target
                    and getattr(target, "id", None)
                    == target_id
                ):
                    return entry

        except Exception as e:
            print(
                f"[AUDIT LOOKUP ERROR] "
                f"{type(e).__name__}: {e}"
            )

        return None


    async def store_audit_entry(entry):
        # Fast in-memory protection during the current process.
        if entry.id in seen_audit_ids:
            return False

        actor_id = (
            entry.user.id
            if entry.user
            else None
        )

        target_id = getattr(safe_audit_target(entry), "id", None)

        changes = []

        try:
            for change in entry.changes:
                changes.append(
                    {
                        "before": safe(change.before),
                        "after": safe(change.after),
                    }
                )
        except Exception:
            pass

        async with connect_db(db_path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO audit_events (
                    audit_id,
                    guild_id,
                    action,
                    actor_id,
                    target_id,
                    reason,
                    changes,
                    extra,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    source_guild_id,
                    str(entry.action),
                    actor_id,
                    target_id,
                    entry.reason,
                    json.dumps(
                        changes,
                        ensure_ascii=False,
                        default=str,
                    ),
                    safe(entry.extra),
                    entry.created_at.isoformat(),
                ),
            )

            await db.commit()

            # SQLite rowcount == 1 only when this audit entry was
            # actually inserted. 0 means it already existed.
            inserted = cursor.rowcount == 1

        # Cache the ID regardless. If it already existed in SQLite,
        # there is no reason to query it again during this process.
        seen_audit_ids.add(entry.id)

        if len(seen_audit_ids) > 5000:
            seen_audit_ids.clear()
            seen_audit_ids.add(entry.id)

        return inserted


    # ========================================================
    # BAN
    # ========================================================

    @client.listen()
    async def on_member_ban(guild, user):

        if guild.id != source_guild_id:
            return

        entry = await find_recent_audit(
            guild,
            discord.AuditLogAction.ban,
            user.id,
        )

        actor = entry.user if entry else None
        reason = entry.reason if entry else None

        await save_server_event(
            "member_ban",
            target_id=user.id,
            actor_id=actor.id if actor else None,
            data={
                "user": str(user),
                "reason": reason,
            },
        )

        await send_log(
            "bans",
            "🔨 Member Banned",
            (
                f"**User:** {user.mention} (`{user.id}`)\n"
                f"**Moderator:** "
                f"{actor.mention if actor else '`Unknown`'}\n"
                f"**Reason:** `{reason or 'No reason / unavailable'}`"
            ),
        )

        print(f"[BAN] {user} ({user.id})")


    # ========================================================
    # UNBAN
    # ========================================================

    @client.listen()
    async def on_member_unban(guild, user):

        if guild.id != source_guild_id:
            return

        entry = await find_recent_audit(
            guild,
            discord.AuditLogAction.unban,
            user.id,
        )

        actor = entry.user if entry else None
        reason = entry.reason if entry else None

        await save_server_event(
            "member_unban",
            target_id=user.id,
            actor_id=actor.id if actor else None,
            data={
                "user": str(user),
                "reason": reason,
            },
        )

        await send_log(
            "unbans",
            "🔓 Member Unbanned",
            (
                f"**User:** {user.mention} (`{user.id}`)\n"
                f"**Moderator:** "
                f"{actor.mention if actor else '`Unknown`'}\n"
                f"**Reason:** `{reason or 'No reason / unavailable'}`"
            ),
        )

        print(f"[UNBAN] {user} ({user.id})")


    # ========================================================
    # KICK DETECTION
    # ========================================================

    @client.listen()
    async def on_member_remove(member):

        if member.guild.id != source_guild_id:
            return

        entry = await find_recent_audit(
            member.guild,
            discord.AuditLogAction.kick,
            member.id,
        )

        if entry is None:
            return

        actor = entry.user

        await save_server_event(
            "member_kick",
            target_id=member.id,
            actor_id=actor.id if actor else None,
            data={
                "user": str(member),
                "reason": entry.reason,
            },
        )

        await send_log(
            "kicks",
            "🥾 Member Kicked",
            (
                f"**User:** {member.mention} (`{member.id}`)\n"
                f"**Moderator:** "
                f"{actor.mention if actor else '`Unknown`'}\n"
                f"**Reason:** "
                f"`{entry.reason or 'No reason / unavailable'}`"
            ),
        )

        print(f"[KICK] {member} ({member.id})")


    # ========================================================
    # AUDIT LOG POLLER
    # ========================================================

    async def audit_worker():

        await client.wait_until_ready()

        guild = client.get_guild(
            source_guild_id
        )

        if guild is None:
            print("[AUDIT] Source Guild not found.")
            return

        print("[AUDIT] Worker started.")

        while not client.is_closed():

            try:
                entries = []

                async for entry in guild.audit_logs(
                    limit=25
                ):
                    entries.append(entry)

                # Old -> new for readable ordering
                for entry in reversed(entries):

                    is_new = await store_audit_entry(
                        entry
                    )

                    if not is_new:
                        continue

                    actor = entry.user
                    target = safe_audit_target(entry)

                    actor_text = (
                        f"{actor} (`{actor.id}`)"
                        if actor
                        else "Unknown"
                    )

                    target_id = (
                        getattr(target, "id", None)
                        if target
                        else None
                    )

                    target_text = (
                        f"{target} (`{target_id}`)"
                        if target
                        else "Unknown"
                    )

                    await send_log(
                        "audit-log",
                        "📋 Audit Log",
                        (
                            f"**Action:** `{entry.action}`\n"
                            f"**Actor:** {actor_text}\n"
                            f"**Target:** {target_text}\n"
                            f"**Reason:** "
                            f"`{entry.reason or 'None'}`\n"
                            f"**Audit ID:** `{entry.id}`"
                        ),
                    )

                    # Dedicated moderator/admin action feed.
                    await send_log(
                        "moderator-actions",
                        "🛡️ Moderator Action",
                        (
                            f"**Action:** `{entry.action}`\n"
                            f"**Actor:** {actor_text}\n"
                            f"**Target:** {target_text}\n"
                            f"**Reason:** "
                            f"`{entry.reason or 'None'}`\n"
                            f"**Audit ID:** `{entry.id}`"
                        ),
                    )

                    await save_server_event(
                        "audit_log",
                        target_id=target_id,
                        actor_id=(
                            actor.id
                            if actor
                            else None
                        ),
                        data={
                            "audit_id": entry.id,
                            "action": str(
                                entry.action
                            ),
                            "reason": entry.reason,
                        },
                    )

                await asyncio.sleep(5)

            except discord.Forbidden:

                print(
                    "[AUDIT ERROR] "
                    "Missing View Audit Log permission."
                )

                await send_log(
                    "logger-errors",
                    "⚠️ Audit Permission Error",
                    "Big Brain cannot read the Source Guild audit log.",
                )

                return

            except Exception as e:

                print(
                    f"[AUDIT ERROR] "
                    f"{type(e).__name__}: {e}"
                )

                await asyncio.sleep(10)


    @client.listen()
    async def on_ready():
        # Guard against Discord reconnects creating duplicates
        if not hasattr(
            client,
            "_big_brain_audit_task",
        ):
            client._big_brain_audit_task = (
                asyncio.create_task(
                    audit_worker()
                )
            )
