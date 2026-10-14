from datetime import datetime, timezone
import json

import aiosqlite
from database import connect_db


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def setup_message_extras(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    async def save_event(
        event_type,
        target_id=None,
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
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (
                    source_guild_id,
                    event_type,
                    target_id,
                    json.dumps(
                        data or {},
                        ensure_ascii=False,
                        default=str,
                    ),
                    utc_now(),
                ),
            )
            await db.commit()


    # ========================================================
    # BULK DELETE
    # ========================================================

    @client.listen()
    async def on_raw_bulk_message_delete(payload):

        if payload.guild_id != source_guild_id:
            return

        message_ids = list(
            payload.message_ids
        )

        async with connect_db(db_path) as db:

            for message_id in message_ids:
                await db.execute(
                    """
                    UPDATE messages
                    SET deleted = 1,
                        deleted_at = ?
                    WHERE message_id = ?
                    """,
                    (
                        utc_now(),
                        message_id,
                    ),
                )

            await db.commit()

        await save_event(
            "bulk_message_delete",
            payload.channel_id,
            {
                "channel_id": payload.channel_id,
                "message_ids": message_ids,
                "count": len(message_ids),
            },
        )

        preview = ", ".join(
            str(x)
            for x in message_ids[:20]
        )

        await send_log(
            "bulk-delete",
            "💥 Bulk Message Delete",
            (
                f"**Channel ID:** "
                f"`{payload.channel_id}`\n"
                f"**Count:** `{len(message_ids)}`\n"
                f"**Message IDs:** "
                f"`{preview}`"
                + (
                    "\n`... more saved in database`"
                    if len(message_ids) > 20
                    else ""
                )
            ),
        )

        await send_log(
            "messages-purged",
            "🧹 Messages Purged",
            (
                f"**Channel ID:** "
                f"`{payload.channel_id}`\n"
                f"**Messages:** "
                f"`{len(message_ids)}`\n"
                f"Moderator attribution is available "
                f"through the audit logger when Discord "
                f"provides a matching audit entry."
            ),
        )

        print(
            f"[BULK DELETE] "
            f"{len(message_ids)} messages "
            f"in {payload.channel_id}"
        )


    # ========================================================
    # PINS
    # ========================================================

    @client.listen()
    async def on_guild_channel_pins_update(
        channel,
        last_pin,
    ):

        if channel.guild.id != source_guild_id:
            return

        await save_event(
            "pins_update",
            channel.id,
            {
                "channel_id": channel.id,
                "last_pin": (
                    last_pin.isoformat()
                    if last_pin
                    else None
                ),
            },
        )

        await send_log(
            "pins",
            "📌 Pins Updated",
            (
                f"**Channel:** "
                f"{channel.mention}\n"
                f"**Channel ID:** "
                f"`{channel.id}`\n"
                f"**Last Pin:** "
                f"`{last_pin or 'None'}`"
            ),
        )

        print(
            f"[PINS UPDATE] {channel.id}"
        )


    # ========================================================
    # ALL REACTIONS FOR ONE EMOJI REMOVED
    # ========================================================

    @client.listen()
    async def on_raw_reaction_clear_emoji(
        payload,
    ):

        if payload.guild_id != source_guild_id:
            return

        async with connect_db(db_path) as db:
            await db.execute(
                """
                INSERT INTO reactions (
                    message_id,
                    channel_id,
                    user_id,
                    emoji,
                    action,
                    timestamp
                )
                VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (
                    payload.message_id,
                    payload.channel_id,
                    str(payload.emoji),
                    "clear_emoji",
                    utc_now(),
                ),
            )
            await db.commit()

        await send_log(
            "reactions-cleared",
            "🧹 Emoji Reactions Cleared",
            (
                f"**Message ID:** "
                f"`{payload.message_id}`\n"
                f"**Channel ID:** "
                f"`{payload.channel_id}`\n"
                f"**Emoji:** `{payload.emoji}`"
            ),
        )

        print(
            f"[REACTION CLEAR EMOJI] "
            f"{payload.message_id} "
            f"{payload.emoji}"
        )
