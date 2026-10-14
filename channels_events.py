from datetime import datetime, timezone
import json

import aiosqlite
from database import connect_db
import discord


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_json(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        default=str,
    )


def channel_snapshot(channel):
    data = {
        "id": channel.id,
        "name": channel.name,
        "type": str(channel.type),
        "position": channel.position,
        "category_id": (
            channel.category_id
            if hasattr(channel, "category_id")
            else None
        ),
    }

    if hasattr(channel, "topic"):
        data["topic"] = channel.topic

    if hasattr(channel, "nsfw"):
        data["nsfw"] = channel.nsfw

    if hasattr(channel, "slowmode_delay"):
        data["slowmode_delay"] = (
            channel.slowmode_delay
        )

    if hasattr(channel, "bitrate"):
        data["bitrate"] = channel.bitrate

    if hasattr(channel, "user_limit"):
        data["user_limit"] = channel.user_limit

    return data


def overwrite_snapshot(channel):
    result = {}

    try:
        for target, overwrite in (
            channel.overwrites.items()
        ):
            allow, deny = overwrite.pair()

            result[str(target.id)] = {
                "target": str(target),
                "target_type": (
                    "role"
                    if isinstance(
                        target,
                        discord.Role,
                    )
                    else "member"
                ),
                "allow": allow.value,
                "deny": deny.value,
            }

    except Exception:
        pass

    return result


def setup_channel_events(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    async def save_event(
        event_type,
        target_id,
        data,
    ):
        async with connect_db(
            db_path
        ) as db:

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
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (
                    source_guild_id,
                    event_type,
                    target_id,
                    safe_json(data),
                    utc_now(),
                ),
            )

            await db.commit()


    # ========================================================
    # CHANNEL CREATE
    # ========================================================

    @client.listen()
    async def on_guild_channel_create(channel):

        if channel.guild.id != source_guild_id:
            return

        try:
            data = channel_snapshot(channel)

            await save_event(
                "channel_create",
                channel.id,
                data,
            )

            await send_log(
                "channel-created",
                "🆕 Channel Created",
                (
                    f"**Channel:** {channel.mention}\n"
                    f"**Type:** `{channel.type}`\n"
                    f"**Category:** "
                    f"`{channel.category.name if channel.category else 'None'}`"
                ),
            )

            print(
                f"[CHANNEL CREATE] "
                f"{channel.name} ({channel.id})"
            )

        except Exception as e:
            print(
                f"[CHANNEL CREATE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # CHANNEL DELETE
    # ========================================================

    @client.listen()
    async def on_guild_channel_delete(channel):

        if channel.guild.id != source_guild_id:
            return

        try:
            data = channel_snapshot(channel)
            data["overwrites"] = (
                overwrite_snapshot(channel)
            )

            await save_event(
                "channel_delete",
                channel.id,
                data,
            )

            await send_log(
                "channel-deleted",
                "🗑️ Channel Deleted",
                (
                    f"**Channel:** {channel.mention}\n"
                    f"**Name:** `{channel.name}`\n"
                    f"**Type:** `{channel.type}`\n"
                    f"**Category:** "
                    f"`{channel.category.name if channel.category else 'None'}`"
                ),
            )

            print(
                f"[CHANNEL DELETE] "
                f"{channel.name} ({channel.id})"
            )

        except Exception as e:
            print(
                f"[CHANNEL DELETE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # CHANNEL UPDATE
    # ========================================================

    @client.listen()
    async def on_guild_channel_update(
        before,
        after,
    ):

        if after.guild.id != source_guild_id:
            return

        try:
            old = channel_snapshot(before)
            new = channel_snapshot(after)

            old_overwrites = (
                overwrite_snapshot(before)
            )
            new_overwrites = (
                overwrite_snapshot(after)
            )

            changed = {}

            for key in set(old) | set(new):
                if old.get(key) != new.get(key):
                    changed[key] = {
                        "before": old.get(key),
                        "after": new.get(key),
                    }

            if changed:
                await save_event(
                    "channel_update",
                    after.id,
                    {
                        "changes": changed,
                    },
                )

                lines = []

                for key, values in changed.items():
                    lines.append(
                        f"**{key}:** "
                        f"`{values['before']}` → "
                        f"`{values['after']}`"
                    )

                await send_log(
                    "channel-updated",
                    "✏️ Channel Updated",
                    (
                        f"**Channel:** {after.mention} "
                        f"(`{after.id}`)\n\n"
                        + "\n".join(lines)[:3000]
                    ),
                )

                print(
                    f"[CHANNEL UPDATE] "
                    f"{after.name}: "
                    f"{list(changed)}"
                )


            # Permission overwrites separately
            if old_overwrites != new_overwrites:

                await save_event(
                    "channel_permissions",
                    after.id,
                    {
                        "before": old_overwrites,
                        "after": new_overwrites,
                    },
                )

                await send_log(
                    "permission-changes",
                    "🔐 Channel Permissions Changed",
                    (
                        f"**Channel:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"Permission overwrites changed.\n"
                        f"Full before/after snapshot "
                        f"saved in database."
                    ),
                )

                print(
                    f"[PERMISSIONS] "
                    f"{after.name} ({after.id})"
                )


            # Category move gets dedicated log too
            if (
                old.get("category_id")
                != new.get("category_id")
            ):
                await send_log(
                    "category-changes",
                    "📁 Channel Category Changed",
                    (
                        f"**Channel:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"**Before category ID:** "
                        f"`{old.get('category_id')}`\n"
                        f"**After category ID:** "
                        f"`{new.get('category_id')}`"
                    ),
                )

        except Exception as e:
            print(
                f"[CHANNEL UPDATE ERROR] "
                f"{type(e).__name__}: {e}"
            )

            await send_log(
                "logger-errors",
                "⚠️ Channel Update Error",
                (
                    f"**Channel ID:** `{after.id}`\n"
                    f"**Error:** "
                    f"`{type(e).__name__}: {e}`"
                ),
            )


    # ========================================================
    # THREAD CREATE
    # ========================================================

    @client.listen()
    async def on_thread_create(thread):

        if thread.guild.id != source_guild_id:
            return

        try:
            await save_event(
                "thread_create",
                thread.id,
                {
                    "name": thread.name,
                    "parent_id": thread.parent_id,
                    "owner_id": thread.owner_id,
                    "archived": thread.archived,
                    "locked": thread.locked,
                },
            )

            await send_log(
                "threads-created",
                "🧵 Thread Created",
                (
                    f"**Thread:** {thread.mention}\n"
                    f"**Parent ID:** "
                    f"`{thread.parent_id}`\n"
                    f"**Owner ID:** "
                    f"`{thread.owner_id}`"
                ),
            )

            print(
                f"[THREAD CREATE] "
                f"{thread.name} ({thread.id})"
            )

        except Exception as e:
            print(
                f"[THREAD CREATE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # THREAD DELETE
    # ========================================================

    @client.listen()
    async def on_thread_delete(thread):

        if thread.guild.id != source_guild_id:
            return

        try:
            await save_event(
                "thread_delete",
                thread.id,
                {
                    "name": thread.name,
                    "parent_id": thread.parent_id,
                    "owner_id": thread.owner_id,
                },
            )

            await send_log(
                "threads-deleted",
                "🗑️ Thread Deleted",
                (
                    f"**Thread:** {thread.mention}\n"
                    f"**Name:** `{thread.name}`\n"
                    f"**Parent ID:** "
                    f"`{thread.parent_id}`"
                ),
            )

            print(
                f"[THREAD DELETE] "
                f"{thread.name} ({thread.id})"
            )

        except Exception as e:
            print(
                f"[THREAD DELETE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # THREAD UPDATE
    # ========================================================

    @client.listen()
    async def on_thread_update(
        before,
        after,
    ):

        if after.guild.id != source_guild_id:
            return

        try:
            old = {
                "name": before.name,
                "archived": before.archived,
                "locked": before.locked,
                "slowmode_delay": (
                    before.slowmode_delay
                ),
                "auto_archive_duration": (
                    before.auto_archive_duration
                ),
            }

            new = {
                "name": after.name,
                "archived": after.archived,
                "locked": after.locked,
                "slowmode_delay": (
                    after.slowmode_delay
                ),
                "auto_archive_duration": (
                    after.auto_archive_duration
                ),
            }

            changed = {}

            for key in old:
                if old[key] != new[key]:
                    changed[key] = {
                        "before": old[key],
                        "after": new[key],
                    }

            if not changed:
                return

            await save_event(
                "thread_update",
                after.id,
                {
                    "changes": changed,
                },
            )

            lines = []

            for key, values in changed.items():
                lines.append(
                    f"**{key}:** "
                    f"`{values['before']}` → "
                    f"`{values['after']}`"
                )

            await send_log(
                "threads-updated",
                "✏️ Thread Updated",
                (
                    f"**Thread:** {after.mention} "
                    f"(`{after.id}`)\n\n"
                    + "\n".join(lines)
                ),
            )

            print(
                f"[THREAD UPDATE] "
                f"{after.name}: "
                f"{list(changed)}"
            )

        except Exception as e:
            print(
                f"[THREAD UPDATE ERROR] "
                f"{type(e).__name__}: {e}"
            )
