import aiosqlite
from database import connect_db
import discord
from log_labels import (
    channel_label,
    normalize_source_references,
)


def cut(text, limit=700):
    if text is None:
        return "(empty)"

    text = str(text)

    if len(text) > limit:
        return text[:limit] + "..."

    return text


def setup_search_system(
    client,
    source_guild_id,
    archive_guild_id,
    db_path,
):

    async def reply(channel, title, description):
        source_guild = client.get_guild(source_guild_id)
        description = normalize_source_references(
            str(description),
            source_guild,
        )
        embed = discord.Embed(
            title=title,
            description=description[:4000],
        )

        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )


    async def archived_user_label(user_id, member=None):
        return f"<@{user_id}>"


    def allowed_channel(channel, name):
        return (
            channel.guild
            and channel.guild.id == archive_guild_id
            and channel.name == name
        )


    @client.listen()
    async def on_message(message):

        if message.author.bot:
            return

        if not message.guild:
            return

        if message.guild.id != archive_guild_id:
            return

        content = message.content.strip()


        # ====================================================
        # !message MESSAGE_ID
        # ====================================================

        if (
            content.startswith("!message ")
            and allowed_channel(
                message.channel,
                "message-search",
            )
        ):

            value = content.split(
                maxsplit=1
            )[1].strip()

            if not value.isdigit():
                await reply(
                    message.channel,
                    "❌ Invalid Message ID",
                    "Use: `!message MESSAGE_ID`",
                )
                return

            message_id = int(value)

            async with connect_db(
                db_path
            ) as db:

                db.row_factory = (
                    aiosqlite.Row
                )

                async with db.execute(
                    """
                    SELECT *
                    FROM messages
                    WHERE message_id = ?
                    """,
                    (message_id,),
                ) as cursor:

                    row = await cursor.fetchone()

            if row is None:
                await reply(
                    message.channel,
                    "🔎 Message Search",
                    (
                        f"No archived message found "
                        f"for `{message_id}`."
                    ),
                )
                return

            await reply(
                message.channel,
                "💬 Archived Message",
                (
                    f"**Message ID:** "
                    f"`{row['message_id']}`\n"
                    f"**Author:** "
                    f"<@{row['author_id']}>\n"
                    f"**Channel ID:** "
                    f"`{row['channel_id']}`\n"
                    f"**Created:** "
                    f"`{row['created_at']}`\n"
                    f"**Edited:** "
                    f"`{row['edited_at']}`\n"
                    f"**Deleted:** "
                    f"`{bool(row['deleted'])}`\n\n"
                    f"**Content:**\n"
                    f"{cut(row['content'], 1800)}"
                ),
            )

            return


        # ====================================================
        # !user USER_ID
        # ====================================================

        if (
            content.startswith("!user ")
            and allowed_channel(
                message.channel,
                "user-search",
            )
        ):

            value = content.split(
                maxsplit=1
            )[1].strip()

            if not value.isdigit():
                await reply(
                    message.channel,
                    "❌ Invalid User ID",
                    "Use: `!user USER_ID`",
                )
                return

            user_id = int(value)

            async with connect_db(
                db_path
            ) as db:

                db.row_factory = (
                    aiosqlite.Row
                )

                async with db.execute(
                    """
                    SELECT
                        COUNT(*) AS messages,
                        MIN(created_at) AS first_message,
                        MAX(created_at) AS last_message
                    FROM messages
                    WHERE author_id = ?
                    """,
                    (user_id,),
                ) as cursor:

                    stats = (
                        await cursor.fetchone()
                    )

                async with db.execute(
                    """
                    SELECT
                        event_type,
                        old_value,
                        new_value,
                        timestamp
                    FROM member_events
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT 10
                    """,
                    (user_id,),
                ) as cursor:

                    events = (
                        await cursor.fetchall()
                    )

            member = (
                client.get_guild(
                    source_guild_id
                ).get_member(user_id)
                if client.get_guild(
                    source_guild_id
                )
                else None
            )
            user_text = await archived_user_label(
                user_id,
                member,
            )

            event_text = []

            for event in events:
                event_text.append(
                    f"`{event['timestamp']}` "
                    f"**{event['event_type']}**"
                )

            await reply(
                message.channel,
                "👤 User Archive",
                (
                    f"**User:** {user_text}\n"
                    f"**Archived messages:** "
                    f"`{stats['messages']}`\n"
                    f"**First message:** "
                    f"`{stats['first_message']}`\n"
                    f"**Last message:** "
                    f"`{stats['last_message']}`\n\n"
                    f"**Recent member events:**\n"
                    + (
                        "\n".join(event_text)
                        if event_text
                        else "None archived."
                    )
                ),
            )

            return


        # ====================================================
        # !voice USER_ID
        # ====================================================

        if (
            content.startswith("!voice ")
            and allowed_channel(
                message.channel,
                "user-search",
            )
        ):
            value = content.split(
                maxsplit=1
            )[1].strip()

            if not value.isdigit():
                await reply(
                    message.channel,
                    "❌ Invalid User ID",
                    "Use: `!voice USER_ID`",
                )
                return

            user_id = int(value)

            async with connect_db(
                db_path
            ) as db:

                db.row_factory = aiosqlite.Row

                async with db.execute(
                    """
                    SELECT
                        COUNT(*) AS sessions,
                        COALESCE(
                            SUM(duration_seconds),
                            0
                        ) AS total_seconds
                    FROM voice_session_history
                    WHERE guild_id = ?
                      AND user_id = ?
                    """,
                    (
                        source_guild_id,
                        user_id,
                    ),
                ) as cursor:
                    stats = await cursor.fetchone()

                async with db.execute(
                    """
                    SELECT
                        channel_id,
                        SUM(duration_seconds) AS seconds
                    FROM voice_session_history
                    WHERE guild_id = ?
                      AND user_id = ?
                    GROUP BY channel_id
                    ORDER BY seconds DESC
                    LIMIT 1
                    """,
                    (
                        source_guild_id,
                        user_id,
                    ),
                ) as cursor:
                    favorite = await cursor.fetchone()

                async with db.execute(
                    """
                    SELECT
                        channel_id,
                        started_at,
                        ended_at,
                        duration_seconds
                    FROM voice_session_history
                    WHERE guild_id = ?
                      AND user_id = ?
                    ORDER BY ended_at DESC
                    LIMIT 5
                    """,
                    (
                        source_guild_id,
                        user_id,
                    ),
                ) as cursor:
                    recent = await cursor.fetchall()

                async with db.execute(
                    """
                    SELECT
                        channel_id,
                        started_at
                    FROM voice_sessions
                    WHERE guild_id = ?
                      AND user_id = ?
                    LIMIT 1
                    """,
                    (
                        source_guild_id,
                        user_id,
                    ),
                ) as cursor:
                    active = await cursor.fetchone()

            guild = client.get_guild(
                source_guild_id
            )

            member = (
                guild.get_member(user_id)
                if guild
                else None
            )
            user_text = await archived_user_label(
                user_id,
                member,
            )

            def duration(seconds):
                seconds = max(
                    0,
                    int(seconds or 0),
                )

                days, seconds = divmod(
                    seconds,
                    86400,
                )

                hours, seconds = divmod(
                    seconds,
                    3600,
                )

                minutes, seconds = divmod(
                    seconds,
                    60,
                )

                parts = []

                if days:
                    parts.append(f"{days}d")

                if hours or days:
                    parts.append(f"{hours}h")

                if minutes or hours or days:
                    parts.append(f"{minutes}m")

                parts.append(f"{seconds}s")

                return " ".join(parts)

            total_seconds = int(
                stats["total_seconds"] or 0
            )

            current_text = "🔴 Not in voice"

            if active:
                from datetime import (
                    datetime,
                    timezone,
                )

                try:
                    started = datetime.fromisoformat(
                        active["started_at"]
                    )

                    now = datetime.now(
                        timezone.utc
                    )

                    current_seconds = int(
                        (
                            now - started
                        ).total_seconds()
                    )

                except Exception:
                    current_seconds = 0

                channel = (
                    guild.get_channel(
                        active["channel_id"]
                    )
                    if guild
                    else None
                )

                channel_text = (
                    channel_label(channel, channel_id=active["channel_id"])
                    if channel
                    else (
                        channel_label(
                            channel_id=active["channel_id"],
                            fallback_name="Unknown or deleted voice channel",
                        )
                    )
                )

                current_text = (
                    "🟢 In Voice\n"
                    f"**Channel:** {channel_text}\n"
                    f"**Current segment:** "
                    f"`{duration(current_seconds)}`"
                )

            favorite_text = "None yet"

            if favorite:
                channel = (
                    guild.get_channel(
                        favorite["channel_id"]
                    )
                    if guild
                    else None
                )

                channel_name = (
                    channel_label(channel, channel_id=favorite["channel_id"])
                    if channel
                    else channel_label(
                        channel_id=favorite["channel_id"],
                        fallback_name="Unknown or deleted voice channel",
                    )
                )

                favorite_text = (
                    f"{channel_name} — "
                    f"{duration(favorite['seconds'])}"
                )

            recent_lines = []

            for row in recent:
                channel = (
                    guild.get_channel(
                        row["channel_id"]
                    )
                    if guild
                    else None
                )

                channel_name = (
                    channel_label(channel, channel_id=row["channel_id"])
                    if channel
                    else channel_label(
                        channel_id=row["channel_id"],
                        fallback_name="Unknown or deleted voice channel",
                    )
                )

                recent_lines.append(
                    f"• **{channel_name}** — "
                    f"`{duration(row['duration_seconds'])}`"
                )

            recent_text = (
                "\n".join(recent_lines)
                if recent_lines
                else "No completed sessions yet."
            )

            await reply(
                message.channel,
                "🎙️ Voice Statistics",
                (
                    f"**User:** {user_text}\n\n"

                    f"**Current:**\n"
                    f"{current_text}\n\n"

                    f"**Completed segments:** "
                    f"`{stats['sessions']}`\n"
                    f"**Completed voice time:** "
                    f"`{duration(total_seconds)}`\n"
                    f"**Most used channel:** "
                    f"`{favorite_text}`\n\n"

                    f"**Recent voice history:**\n"
                    f"{recent_text}"
                ),
            )

            return

        # ====================================================
        # !history USER_ID
        # ====================================================

        if (
            content.startswith("!history ")
            and allowed_channel(
                message.channel,
                "history-search",
            )
        ):

            value = content.split(
                maxsplit=1
            )[1].strip()

            if not value.isdigit():
                await reply(
                    message.channel,
                    "❌ Invalid User ID",
                    "Use: `!history USER_ID`",
                )
                return

            user_id = int(value)

            async with connect_db(
                db_path
            ) as db:

                db.row_factory = (
                    aiosqlite.Row
                )

                async with db.execute(
                    """
                    SELECT
                        message_id,
                        channel_id,
                        content,
                        created_at,
                        deleted
                    FROM messages
                    WHERE author_id = ?
                    ORDER BY created_at DESC
                    LIMIT 15
                    """,
                    (user_id,),
                ) as cursor:

                    rows = (
                        await cursor.fetchall()
                    )

            if not rows:
                await reply(
                    message.channel,
                    "📚 User History",
                    (
                        f"No messages archived "
                        f"for `{user_id}`."
                    ),
                )
                return

            lines = []

            for row in rows:
                marker = (
                    "🗑️"
                    if row["deleted"]
                    else "💬"
                )

                lines.append(
                    f"{marker} "
                    f"`{row['message_id']}` "
                    f"<#{row['channel_id']}>\n"
                    f"{cut(row['content'], 150)}"
                )

            await reply(
                message.channel,
                "📚 Recent Message History",
                "\n\n".join(lines),
            )

            return


        # ====================================================
        # !search TEXT
        # ====================================================

        if (
            content.startswith("!search ")
            and allowed_channel(
                message.channel,
                "message-search",
            )
        ):

            query = content.split(
                maxsplit=1
            )[1].strip()

            if len(query) < 2:
                await reply(
                    message.channel,
                    "❌ Search Too Short",
                    (
                        "Use at least "
                        "2 characters."
                    ),
                )
                return

            async with connect_db(
                db_path
            ) as db:

                db.row_factory = (
                    aiosqlite.Row
                )

                async with db.execute(
                    """
                    SELECT
                        message_id,
                        channel_id,
                        author_id,
                        author_name,
                        content,
                        created_at,
                        deleted
                    FROM messages
                    WHERE content LIKE ?
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    (
                        f"%{query}%",
                    ),
                ) as cursor:

                    rows = (
                        await cursor.fetchall()
                    )

            if not rows:
                await reply(
                    message.channel,
                    "🔎 Text Search",
                    (
                        f"No archived results "
                        f"for `{cut(query, 100)}`."
                    ),
                )
                return

            lines = []

            for row in rows:
                deleted = (
                    " 🗑️"
                    if row["deleted"]
                    else ""
                )

                lines.append(
                    f"**<@{row['author_id']}>**"
                    f"{deleted}\n"
                    f"`{row['message_id']}` "
                    f"<#{row['channel_id']}>\n"
                    f"{cut(row['content'], 180)}"
                )

            await reply(
                message.channel,
                f"🔎 Search: {cut(query, 100)}",
                "\n\n".join(lines),
            )
