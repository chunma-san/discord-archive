import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import aiosqlite
import discord
from discord.ext import commands
from system_status import setup_system_status
from automod_events import setup_automod_events
from message_content_events import setup_message_content_events
from dotenv import load_dotenv

from database import DB_PATH, connect_db, init_database
from social_events import setup_social_events
from presence_voice import setup_presence_voice
from moderation import setup_moderation
from channels_events import setup_channel_events
from roles_events import setup_role_events
from server_events import setup_server_events
from message_extras import setup_message_extras
from search_system import setup_search_system
from voice_dashboard import setup_voice_dashboard
from security_trap import setup_security_trap
from log_labels import normalize_source_references


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
SOURCE_GUILD_ID = int(os.getenv("SOURCE_GUILD_ID"))
ARCHIVE_GUILD_ID = int(os.getenv("ARCHIVE_GUILD_ID"))

ATTACHMENTS_DIR = Path("data/attachments")
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# DISCORD INTENTS
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = True
intents.messages = True
intents.reactions = True
intents.voice_states = True

client = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def clean_codeblock(text):
    """
    Prevent message content from breaking Discord code blocks.
    """
    if not text:
        return "[No text content]"

    return text.replace("```", "'''") 


async def archive_channel(name):
    """
    Find a text channel inside Archive Guild by name.
    """
    guild = client.get_guild(ARCHIVE_GUILD_ID)

    if guild is None:
        return None

    matches = [
        channel
        for channel in guild.text_channels
        if channel.name == name
    ]

    if len(matches) > 1:
        print(
            f"[LOG ROUTING ERROR] More than one archive channel "
            f"is named #{name}; refusing to send to an arbitrary channel."
        )
        return None

    return matches[0] if matches else None


async def send_log(channel_name, title, description):
    """
    Send an embed to a logging channel inside Archive Guild.
    """
    channel = await archive_channel(channel_name)

    if channel is None:
        print(f"[WARNING] Archive Guild channel not found: #{channel_name}")
        return

    source_guild = client.get_guild(SOURCE_GUILD_ID)
    description = normalize_source_references(
        str(description),
        source_guild,
    )

    embed = discord.Embed(
        title=title,
        description=description[:4000],
        timestamp=datetime.now(timezone.utc),
    )

    for attempt in range(3):
        try:
            await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        except discord.HTTPException as e:
            retryable = e.status == 429 or e.status >= 500
            if not retryable or attempt == 2:
                print(
                    f"[LOG ERROR] #{channel_name}: "
                    f"{type(e).__name__}: {e}"
                )
                return

            retry_after = getattr(e, "retry_after", None)
            if retry_after is None:
                response = getattr(e, "response", None)
                headers = getattr(response, "headers", {})
                retry_after = headers.get("Retry-After")
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = 2 ** (attempt + 1)
            await asyncio.sleep(min(30.0, max(1.0, delay)))

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == 2:
                print(
                    f"[LOG ERROR] #{channel_name}: "
                    f"{type(e).__name__}: {e}"
                )
                return
            await asyncio.sleep(2 ** (attempt + 1))

        except Exception as e:
            print(
                f"[LOG ERROR] #{channel_name}: "
                f"{type(e).__name__}: {e}"
            )
            return


# ============================================================
# DATABASE - MESSAGES
# ============================================================

async def save_message(message):
    """
    Save/update a message in the database.
    """

    reply_id = None

    if message.reference:
        reply_id = message.reference.message_id

    async with connect_db(DB_PATH) as db:

        await db.execute(
            """
            INSERT INTO messages (
                message_id,
                guild_id,
                channel_id,
                author_id,
                author_name,
                author_display_name,
                content,
                created_at,
                edited_at,
                reply_to_message_id,
                is_bot,
                is_webhook,
                is_pinned,
                deleted,
                deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)

            ON CONFLICT(message_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_id = excluded.channel_id,
                author_id = excluded.author_id,
                author_name = excluded.author_name,
                author_display_name = excluded.author_display_name,
                content = excluded.content,
                edited_at = excluded.edited_at,
                reply_to_message_id = excluded.reply_to_message_id,
                is_bot = excluded.is_bot,
                is_webhook = excluded.is_webhook,
                is_pinned = excluded.is_pinned
            """,
            (
                message.id,
                message.guild.id,
                message.channel.id,
                message.author.id,
                str(message.author),
                message.author.display_name,
                message.content,
                message.created_at.isoformat(),
                (
                    message.edited_at.isoformat()
                    if message.edited_at
                    else None
                ),
                reply_id,
                int(message.author.bot),
                int(message.webhook_id is not None),
                int(message.pinned),
            ),
        )

        await db.commit()


# ============================================================
# ATTACHMENTS
# ============================================================

async def save_attachments(message):
    """
    Download every attachment locally and store metadata
    in the database.
    """

    if not message.attachments:
        return

    message_dir = (
        ATTACHMENTS_DIR
        / str(message.channel.id)
        / str(message.id)
    )

    message_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(timeout=timeout) as session:

        for attachment in message.attachments:

            # Avoid path traversal / weird filenames
            safe_name = Path(attachment.filename).name

            local_path = (
                message_dir
                / f"{attachment.id}_{safe_name}"
            )

            try:

                # Don't download twice
                if not local_path.exists():

                    async with session.get(
                        attachment.url
                    ) as response:

                        if response.status != 200:
                            print(
                                "[ATTACHMENT ERROR] "
                                f"HTTP {response.status}: "
                                f"{attachment.filename}"
                            )
                            continue

                        with open(local_path, "wb") as f:

                            async for chunk in (
                                response.content.iter_chunked(
                                    1024 * 1024
                                )
                            ):
                                f.write(chunk)

                # Save attachment metadata
                async with connect_db(DB_PATH) as db:

                    await db.execute(
                        """
                        INSERT INTO attachments (
                            attachment_id,
                            message_id,
                            filename,
                            content_type,
                            size,
                            original_url,
                            proxy_url,
                            local_path,
                            width,
                            height,
                            saved_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                        ON CONFLICT(attachment_id)
                        DO UPDATE SET
                            message_id = excluded.message_id,
                            filename = excluded.filename,
                            content_type = excluded.content_type,
                            size = excluded.size,
                            original_url = excluded.original_url,
                            proxy_url = excluded.proxy_url,
                            local_path = excluded.local_path,
                            width = excluded.width,
                            height = excluded.height
                        """,
                        (
                            attachment.id,
                            message.id,
                            attachment.filename,
                            attachment.content_type,
                            attachment.size,
                            attachment.url,
                            attachment.proxy_url,
                            str(local_path),
                            attachment.width,
                            attachment.height,
                            now(),
                        ),
                    )

                    await db.commit()

                print(
                    f"[ATTACHMENT] "
                    f"{attachment.filename} "
                    f"-> {local_path}"
                )

                description = (
                    f"**User:** {message.author.mention} "
                    f"(`{message.author.id}`)\n"
                    f"**Channel:** {message.channel.mention} "
                    f"(`{message.channel.id}`)\n"
                    f"**Message ID:** `{message.id}`\n"
                    f"**Attachment ID:** `{attachment.id}`\n"
                    f"**File:** `{attachment.filename}`\n"
                    f"**Type:** "
                    f"`{attachment.content_type or 'Unknown'}`\n"
                    f"**Size:** `{attachment.size}` bytes\n"
                    f"**Saved:** `{local_path}`"
                )

                await send_log(
                    "attachments",
                    "📎 Attachment Archived",
                    description,
                )

            except Exception as e:

                print(
                    "[ATTACHMENT ERROR] "
                    f"{attachment.filename}: "
                    f"{type(e).__name__}: {e}"
                )

                await send_log(
                    "logger-errors",
                    "⚠️ Attachment Error",
                    (
                        f"**Message ID:** `{message.id}`\n"
                        f"**Attachment:** "
                        f"`{attachment.filename}`\n"
                        f"**Error:** "
                        f"`{type(e).__name__}: {e}`"
                    ),
                )



setup_social_events(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)



setup_presence_voice(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)



setup_moderation(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)



setup_channel_events(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)



setup_role_events(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)



setup_server_events(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)



setup_message_extras(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)






setup_system_status(
    client=client,
    db_path=DB_PATH,
    send_log=send_log,
)


setup_automod_events(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    db_path=DB_PATH,
    send_log=send_log,
)


setup_message_content_events(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    send_log=send_log,
)


setup_search_system(
    client=client,
    source_guild_id=SOURCE_GUILD_ID,
    archive_guild_id=ARCHIVE_GUILD_ID,
    db_path=DB_PATH,
)

setup_voice_dashboard(
    client,
    SOURCE_GUILD_ID,
    ARCHIVE_GUILD_ID,
)

setup_security_trap(
    client,
    SOURCE_GUILD_ID,
    ARCHIVE_GUILD_ID,
)




# ============================================================
# READY
# ============================================================

@client.event
async def on_ready():

    await init_database()

    source = client.get_guild(SOURCE_GUILD_ID)
    archive = client.get_guild(ARCHIVE_GUILD_ID)

    print("=" * 60)
    print(f"BIG BRAIN ONLINE: {client.user}")
    print(
        f"Source Guild : "
        f"{source.name if source else 'NOT FOUND'}"
    )
    print(
        f"Archive Guild: "
        f"{archive.name if archive else 'NOT FOUND'}"
    )
    print("=" * 60)

    await send_log(
        "logger-status",
        "🧠 Big Brain Online",
        (
            f"**Source Guild:** "
            f"`{source.name if source else 'NOT FOUND'}`\n"
            f"**Source Guild ID:** `{SOURCE_GUILD_ID}`\n"
            f"**Archive Guild:** "
            f"`{archive.name if archive else 'NOT FOUND'}`"
        ),
    )


# ============================================================
# NEW MESSAGE
# ============================================================

@client.event
async def on_message(message):

    # Ignore DMs
    if message.guild is None:
        return

    # Monitor Source Guild only
    if message.guild.id != SOURCE_GUILD_ID:
        return

    try:

        await save_message(message)

        await save_attachments(message)

        print(
            f"[MESSAGE] "
            f"{message.author} "
            f"#{message.channel} "
            f"{message.id}"
        )

    except Exception as e:

        print(
            f"[MESSAGE ERROR] "
            f"{type(e).__name__}: {e}"
        )

        await send_log(
            "logger-errors",
            "⚠️ Message Save Error",
            (
                f"**Message ID:** `{message.id}`\n"
                f"**Channel ID:** `{message.channel.id}`\n"
                f"**Error:** "
                f"`{type(e).__name__}: {e}`"
            ),
        )


# ============================================================
# MESSAGE EDIT
# ============================================================

@client.event
async def on_message_edit(before, after):

    if after.guild is None:
        return

    if after.guild.id != SOURCE_GUILD_ID:
        return

    # Ignore events where content itself did not change
    if before.content == after.content:
        return

    try:

        edit_time = now()

        async with connect_db(DB_PATH) as db:

            # Store full edit history
            await db.execute(
                """
                INSERT INTO message_edits (
                    message_id,
                    old_content,
                    new_content,
                    edited_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    after.id,
                    before.content,
                    after.content,
                    edit_time,
                ),
            )

            # Update current message version
            await db.execute(
                """
                UPDATE messages
                SET content = ?,
                    edited_at = ?
                WHERE message_id = ?
                """,
                (
                    after.content,
                    edit_time,
                    after.id,
                ),
            )

            await db.commit()

        old_content = clean_codeblock(
            before.content
        )[:1500]

        new_content = clean_codeblock(
            after.content
        )[:1500]

        description = (
            f"**User:** {after.author.mention} "
            f"(`{after.author.id}`)\n"
            f"**Channel:** {after.channel.mention} "
            f"(`{after.channel.id}`)\n"
            f"**Message ID:** `{after.id}`\n\n"

            f"**BEFORE**\n"
            f"```text\n{old_content}\n```\n"

            f"**AFTER**\n"
            f"```text\n{new_content}\n```"
        )

        await send_log(
            "message-edited",
            "✏️ Message Edited",
            description,
        )

        print(
            f"[EDIT] {after.id}"
        )

    except Exception as e:

        print(
            f"[EDIT ERROR] "
            f"{type(e).__name__}: {e}"
        )

        await send_log(
            "logger-errors",
            "⚠️ Message Edit Error",
            (
                f"**Message ID:** `{after.id}`\n"
                f"**Error:** "
                f"`{type(e).__name__}: {e}`"
            ),
        )


# ============================================================
# CACHED MESSAGE DELETE
# ============================================================

@client.event
async def on_message_delete(message):

    if message.guild is None:
        return

    if message.guild.id != SOURCE_GUILD_ID:
        return

    try:

        delete_time = now()

        async with connect_db(DB_PATH) as db:

            await db.execute(
                """
                UPDATE messages
                SET deleted = 1,
                    deleted_at = ?
                WHERE message_id = ?
                """,
                (
                    delete_time,
                    message.id,
                ),
            )

            await db.commit()

        content = clean_codeblock(
            message.content
        )[:2500]

        description = (
            f"**User:** {message.author.mention} "
            f"(`{message.author.id}`)\n"
            f"**Channel:** {message.channel.mention} "
            f"(`{message.channel.id}`)\n"
            f"**Message ID:** `{message.id}`\n"
            f"**Created:** "
            f"<t:{int(message.created_at.timestamp())}:F>\n\n"

            f"**CONTENT**\n"
            f"```text\n{content}\n```"
        )

        await send_log(
            "message-deleted",
            "🗑️ Message Deleted",
            description,
        )

        print(
            f"[DELETE] {message.id}"
        )

    except Exception as e:

        print(
            f"[DELETE ERROR] "
            f"{type(e).__name__}: {e}"
        )

        await send_log(
            "logger-errors",
            "⚠️ Message Delete Error",
            (
                f"**Message ID:** `{message.id}`\n"
                f"**Error:** "
                f"`{type(e).__name__}: {e}`"
            ),
        )


# ============================================================
# RAW / UNCACHED MESSAGE DELETE
# ============================================================

@client.event
async def on_raw_message_delete(payload):

    if payload.guild_id != SOURCE_GUILD_ID:
        return

    # on_message_delete already handled this one
    if payload.cached_message is not None:
        return

    try:

        delete_time = now()

        async with connect_db(DB_PATH) as db:

            cursor = await db.execute(
                """
                SELECT
                    author_id,
                    author_name,
                    content,
                    created_at
                FROM messages
                WHERE message_id = ?
                """,
                (
                    payload.message_id,
                ),
            )

            row = await cursor.fetchone()

            await db.execute(
                """
                UPDATE messages
                SET deleted = 1,
                    deleted_at = ?
                WHERE message_id = ?
                """,
                (
                    delete_time,
                    payload.message_id,
                ),
            )

            await db.commit()

        if row:

            author_id = row[0]
            author_name = row[1]
            content = clean_codeblock(
                row[2]
            )[:2500]
            created_at = row[3]

            description = (
                f"**User:** <@{author_id}> "
                f"(`{author_id}`)\n"
                f"**Channel ID:** "
                f"`{payload.channel_id}`\n"
                f"**Message ID:** "
                f"`{payload.message_id}`\n"
                f"**Created:** `{created_at}`\n"
                f"**Cache:** "
                f"`UNCACHED - recovered from database`\n\n"

                f"**CONTENT**\n"
                f"```text\n{content}\n```"
            )

        else:

            description = (
                f"**Channel ID:** "
                f"`{payload.channel_id}`\n"
                f"**Message ID:** "
                f"`{payload.message_id}`\n"
                f"**Cache:** `UNCACHED`\n\n"
                f"⚠️ Message was not previously stored "
                f"in the Big Brain database."
            )

        await send_log(
            "message-deleted",
            "🗑️ Raw Message Deleted",
            description,
        )

        print(
            f"[RAW DELETE] "
            f"{payload.message_id}"
        )

    except Exception as e:

        print(
            f"[RAW DELETE ERROR] "
            f"{type(e).__name__}: {e}"
        )

        await send_log(
            "logger-errors",
            "⚠️ Raw Delete Error",
            (
                f"**Message ID:** "
                f"`{payload.message_id}`\n"
                f"**Error:** "
                f"`{type(e).__name__}: {e}`"
            ),
        )


# ============================================================
# START
# ============================================================

async def main():

    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing from .env"
        )

    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("\nBig Brain stopped.")
