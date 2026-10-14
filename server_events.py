from datetime import datetime, timezone
import json

import aiosqlite
from database import connect_db


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def dumps(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        default=str,
    )


def ids(items):
    return [x.id for x in items]


def setup_server_events(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    async def save(
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
                    dumps(data or {}),
                    utc_now(),
                ),
            )
            await db.commit()


    # ========================================================
    # GUILD UPDATE
    # ========================================================

    @client.listen()
    async def on_guild_update(before, after):

        if after.id != source_guild_id:
            return

        fields = [
            "name",
            "description",
            "verification_level",
            "explicit_content_filter",
            "afk_timeout",
            "preferred_locale",
            "mfa_level",
            "nsfw_level",
            "premium_tier",
        ]

        changes = {}

        for field in fields:
            old = getattr(before, field, None)
            new = getattr(after, field, None)

            if old != new:
                changes[field] = {
                    "before": str(old),
                    "after": str(new),
                }

        if not changes:
            return

        await save(
            "guild_update",
            after.id,
            {"changes": changes},
        )

        lines = []

        for key, value in changes.items():
            lines.append(
                f"**{key}:** "
                f"`{value['before']}` → "
                f"`{value['after']}`"
            )

        await send_log(
            "server-updates",
            "🏠 Server Updated",
            "\n".join(lines)[:3500],
        )

        print(
            f"[SERVER UPDATE] {list(changes)}"
        )


    # ========================================================
    # EMOJIS
    # ========================================================

    @client.listen()
    async def on_guild_emojis_update(
        guild,
        before,
        after,
    ):

        if guild.id != source_guild_id:
            return

        before_map = {x.id: x for x in before}
        after_map = {x.id: x for x in after}

        added = (
            set(after_map)
            - set(before_map)
        )

        removed = (
            set(before_map)
            - set(after_map)
        )

        changed = []

        for emoji_id in (
            set(before_map)
            & set(after_map)
        ):
            old = before_map[emoji_id]
            new = after_map[emoji_id]

            if (
                old.name != new.name
                or old.available != new.available
            ):
                changed.append(
                    {
                        "id": emoji_id,
                        "before_name": old.name,
                        "after_name": new.name,
                        "before_available": (
                            old.available
                        ),
                        "after_available": (
                            new.available
                        ),
                    }
                )

        data = {
            "added": [
                {
                    "id": x,
                    "name": after_map[x].name,
                }
                for x in added
            ],
            "removed": [
                {
                    "id": x,
                    "name": before_map[x].name,
                }
                for x in removed
            ],
            "changed": changed,
        }

        await save(
            "emoji_update",
            guild.id,
            data,
        )

        await send_log(
            "emoji-changes",
            "😀 Emoji Changes",
            (
                f"**Added:** `{len(added)}`\n"
                f"**Removed:** `{len(removed)}`\n"
                f"**Changed:** `{len(changed)}`\n\n"
                f"Full details saved in database."
            ),
        )

        print(
            "[EMOJI] "
            f"+{len(added)} "
            f"-{len(removed)} "
            f"~{len(changed)}"
        )


    # ========================================================
    # STICKERS
    # ========================================================

    @client.listen()
    async def on_guild_stickers_update(
        guild,
        before,
        after,
    ):

        if guild.id != source_guild_id:
            return

        before_map = {x.id: x for x in before}
        after_map = {x.id: x for x in after}

        added = (
            set(after_map)
            - set(before_map)
        )

        removed = (
            set(before_map)
            - set(after_map)
        )

        common = (
            set(before_map)
            & set(after_map)
        )

        changed = []

        for sticker_id in common:
            old = before_map[sticker_id]
            new = after_map[sticker_id]

            if (
                old.name != new.name
                or old.description
                != new.description
            ):
                changed.append(sticker_id)

        await save(
            "sticker_update",
            guild.id,
            {
                "added": list(added),
                "removed": list(removed),
                "changed": changed,
            },
        )

        await send_log(
            "sticker-changes",
            "🏷️ Sticker Changes",
            (
                f"**Added:** `{len(added)}`\n"
                f"**Removed:** `{len(removed)}`\n"
                f"**Changed:** `{len(changed)}`"
            ),
        )

        print(
            "[STICKER] "
            f"+{len(added)} "
            f"-{len(removed)} "
            f"~{len(changed)}"
        )


    # ========================================================
    # INVITES
    # ========================================================

    @client.listen()
    async def on_invite_create(invite):

        guild = invite.guild

        if (
            guild is None
            or guild.id != source_guild_id
        ):
            return

        inviter = invite.inviter

        await save(
            "invite_create",
            None,
            {
                "code": invite.code,
                "channel_id": (
                    invite.channel.id
                    if invite.channel
                    else None
                ),
                "inviter_id": (
                    inviter.id
                    if inviter
                    else None
                ),
                "max_age": invite.max_age,
                "max_uses": invite.max_uses,
                "temporary": invite.temporary,
            },
        )

        await send_log(
            "invite-created",
            "🔗 Invite Created",
            (
                f"**Code:** `{invite.code}`\n"
                f"**Channel:** "
                f"`{invite.channel}`\n"
                f"**Creator:** "
                f"{inviter.mention if inviter else '`Unknown`'}\n"
                f"**Max Uses:** `{invite.max_uses}`\n"
                f"**Max Age:** `{invite.max_age}`"
            ),
        )

        print(
            f"[INVITE CREATE] {invite.code}"
        )


    @client.listen()
    async def on_invite_delete(invite):

        guild = invite.guild

        if (
            guild is None
            or guild.id != source_guild_id
        ):
            return

        await save(
            "invite_delete",
            None,
            {
                "code": invite.code,
                "channel_id": (
                    invite.channel.id
                    if invite.channel
                    else None
                ),
            },
        )

        await send_log(
            "invite-deleted",
            "🗑️ Invite Deleted",
            (
                f"**Code:** `{invite.code}`\n"
                f"**Channel:** "
                f"`{invite.channel}`"
            ),
        )

        print(
            f"[INVITE DELETE] {invite.code}"
        )


    # ========================================================
    # SCHEDULED EVENTS
    # ========================================================

    @client.listen()
    async def on_scheduled_event_create(event):

        if event.guild_id != source_guild_id:
            return

        await save(
            "scheduled_event_create",
            event.id,
            {
                "name": event.name,
                "description": (
                    event.description
                ),
                "start": (
                    event.start_time.isoformat()
                    if event.start_time
                    else None
                ),
                "end": (
                    event.end_time.isoformat()
                    if event.end_time
                    else None
                ),
            },
        )

        await send_log(
            "scheduled-events",
            "📅 Scheduled Event Created",
            (
                f"**Name:** `{event.name}`\n"
                f"**ID:** `{event.id}`\n"
                f"**Start:** "
                f"`{event.start_time}`"
            ),
        )

        print(
            f"[EVENT CREATE] "
            f"{event.name}"
        )


    @client.listen()
    async def on_scheduled_event_delete(event):

        if event.guild_id != source_guild_id:
            return

        await save(
            "scheduled_event_delete",
            event.id,
            {
                "name": event.name,
            },
        )

        await send_log(
            "scheduled-events",
            "🗑️ Scheduled Event Deleted",
            (
                f"**Name:** `{event.name}`\n"
                f"**ID:** `{event.id}`"
            ),
        )

        print(
            f"[EVENT DELETE] "
            f"{event.name}"
        )


    @client.listen()
    async def on_scheduled_event_update(
        before,
        after,
    ):

        if after.guild_id != source_guild_id:
            return

        fields = [
            "name",
            "description",
            "status",
            "location",
            "start_time",
            "end_time",
        ]

        changes = {}

        for field in fields:
            old = getattr(
                before,
                field,
                None,
            )
            new = getattr(
                after,
                field,
                None,
            )

            if old != new:
                changes[field] = {
                    "before": str(old),
                    "after": str(new),
                }

        if not changes:
            return

        await save(
            "scheduled_event_update",
            after.id,
            {
                "changes": changes,
            },
        )

        await send_log(
            "scheduled-events",
            "✏️ Scheduled Event Updated",
            (
                f"**Event:** `{after.name}`\n"
                f"**ID:** `{after.id}`\n"
                f"**Changed:** "
                f"`{', '.join(changes)}`"
            ),
        )

        print(
            f"[EVENT UPDATE] "
            f"{after.name}: {list(changes)}"
        )


    # ========================================================
    # STAGE INSTANCE
    # ========================================================

    @client.listen()
    async def on_stage_instance_create(stage):

        if stage.guild.id != source_guild_id:
            return

        await save(
            "stage_create",
            stage.id,
            {
                "channel_id": stage.channel_id,
                "topic": stage.topic,
                "privacy_level": (
                    str(stage.privacy_level)
                ),
            },
        )

        await send_log(
            "stage-events",
            "🎙️ Stage Started",
            (
                f"**Topic:** `{stage.topic}`\n"
                f"**Stage ID:** `{stage.id}`\n"
                f"**Channel ID:** "
                f"`{stage.channel_id}`"
            ),
        )

        print(
            f"[STAGE CREATE] {stage.id}"
        )


    @client.listen()
    async def on_stage_instance_delete(stage):

        if stage.guild.id != source_guild_id:
            return

        await save(
            "stage_delete",
            stage.id,
            {
                "channel_id": stage.channel_id,
                "topic": stage.topic,
            },
        )

        await send_log(
            "stage-events",
            "🛑 Stage Ended",
            (
                f"**Topic:** `{stage.topic}`\n"
                f"**Stage ID:** `{stage.id}`"
            ),
        )

        print(
            f"[STAGE DELETE] {stage.id}"
        )


    @client.listen()
    async def on_stage_instance_update(
        before,
        after,
    ):

        if after.guild.id != source_guild_id:
            return

        changes = {}

        for field in [
            "topic",
            "privacy_level",
        ]:
            old = getattr(before, field, None)
            new = getattr(after, field, None)

            if old != new:
                changes[field] = {
                    "before": str(old),
                    "after": str(new),
                }

        if not changes:
            return

        await save(
            "stage_update",
            after.id,
            {"changes": changes},
        )

        await send_log(
            "stage-events",
            "✏️ Stage Updated",
            (
                f"**Stage ID:** `{after.id}`\n"
                f"**Changed:** "
                f"`{', '.join(changes)}`"
            ),
        )

        print(
            f"[STAGE UPDATE] "
            f"{after.id}: {list(changes)}"
        )


    # ========================================================
    # WEBHOOK CHANGES
    # ========================================================

    @client.listen()
    async def on_webhooks_update(channel):

        if channel.guild.id != source_guild_id:
            return

        await save(
            "webhooks_update",
            channel.id,
            {
                "channel_id": channel.id,
                "channel_name": channel.name,
            },
        )

        await send_log(
            "webhook-changes",
            "🪝 Webhook Change Detected",
            (
                f"**Channel:** {channel.mention}\n"
                f"**Channel ID:** "
                f"`{channel.id}`\n"
                f"Webhook state changed. "
                f"Audit log contains actor/details "
                f"when Discord exposes them."
            ),
        )

        print(
            f"[WEBHOOK UPDATE] "
            f"{channel.name}"
        )
