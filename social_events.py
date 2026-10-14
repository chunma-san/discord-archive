from datetime import datetime, timezone
import json

import aiosqlite
from database import connect_db
import discord


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def activity_text(member):
    activities = []

    for activity in member.activities:
        try:
            data = {
                "type": str(activity.type),
                "name": getattr(activity, "name", None),
            }

            details = getattr(activity, "details", None)
            state = getattr(activity, "state", None)

            if details:
                data["details"] = details

            if state:
                data["state"] = state

            activities.append(data)

        except Exception:
            continue

    return json.dumps(
        activities,
        ensure_ascii=False,
    )


def role_ids(member):
    return {
        role.id
        for role in member.roles
        if not role.is_default()
    }


def setup_social_events(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    # ========================================================
    # DATABASE HELPERS
    # ========================================================

    async def member_event(
        user_id,
        event_type,
        old_value=None,
        new_value=None,
    ):
        async with connect_db(db_path) as db:

            await db.execute(
                """
                INSERT INTO member_events (
                    guild_id,
                    user_id,
                    event_type,
                    old_value,
                    new_value,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_guild_id,
                    user_id,
                    event_type,
                    old_value,
                    new_value,
                    utc_now(),
                ),
            )

            await db.commit()


    async def reaction_event(
        message_id,
        channel_id,
        user_id,
        emoji,
        action,
    ):
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
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    channel_id,
                    user_id,
                    str(emoji),
                    action,
                    utc_now(),
                ),
            )

            await db.commit()


    # ========================================================
    # MEMBER JOIN
    # ========================================================

    @client.listen()
    async def on_member_join(member):

        if member.guild.id != source_guild_id:
            return

        try:
            await member_event(
                member.id,
                "member_join",
                None,
                str(member),
            )

            account_created = int(
                member.created_at.timestamp()
            )

            description = (
                f"**User:** {member.mention}\n"
                f"**Username:** `{member}`\n"
                f"**User ID:** `{member.id}`\n"
                f"**Bot:** `{member.bot}`\n"
                f"**Account created:** "
                f"<t:{account_created}:F>\n"
                f"**Account age:** "
                f"<t:{account_created}:R>"
            )

            await send_log(
                "member-join",
                "📥 Member Joined",
                description,
            )

            print(
                f"[MEMBER JOIN] "
                f"{member} ({member.id})"
            )

        except Exception as e:
            print(
                f"[MEMBER JOIN ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # MEMBER LEAVE
    # ========================================================

    @client.listen()
    async def on_member_remove(member):

        if member.guild.id != source_guild_id:
            return

        try:
            roles = [
                role.name
                for role in member.roles
                if not role.is_default()
            ]

            await member_event(
                member.id,
                "member_leave",
                str(member),
                None,
            )

            joined = (
                f"<t:{int(member.joined_at.timestamp())}:F>"
                if member.joined_at
                else "Unknown"
            )

            description = (
                f"**User:** `{member}`\n"
                f"**User ID:** `{member.id}`\n"
                f"**Display name:** "
                f"`{member.display_name}`\n"
                f"**Joined server:** {joined}\n"
                f"**Roles:** "
                f"`{', '.join(roles) if roles else 'None'}`"
            )

            await send_log(
                "member-leave",
                "📤 Member Left",
                description,
            )

            print(
                f"[MEMBER LEAVE] "
                f"{member} ({member.id})"
            )

        except Exception as e:
            print(
                f"[MEMBER LEAVE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # MEMBER UPDATE
    # ========================================================

    @client.listen()
    async def on_member_update(before, after):

        if after.guild.id != source_guild_id:
            return

        try:

            # ------------------------------------------------
            # NICKNAME
            # ------------------------------------------------

            if before.nick != after.nick:

                await member_event(
                    after.id,
                    "nickname_change",
                    before.nick,
                    after.nick,
                )

                await send_log(
                    "nickname-changes",
                    "🏷️ Nickname Changed",
                    (
                        f"**User:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"**Before:** "
                        f"`{before.nick or 'None'}`\n"
                        f"**After:** "
                        f"`{after.nick or 'None'}`"
                    ),
                )

                print(
                    f"[NICKNAME] {after.id}: "
                    f"{before.nick} -> {after.nick}"
                )


            # ------------------------------------------------
            # ROLES
            # ------------------------------------------------

            before_roles = role_ids(before)
            after_roles = role_ids(after)

            added = after_roles - before_roles
            removed = before_roles - after_roles

            for role_id in added:

                role = after.guild.get_role(role_id)

                role_name = (
                    role.name
                    if role
                    else "Unknown Role"
                )

                await member_event(
                    after.id,
                    "role_added",
                    None,
                    json.dumps(
                        {
                            "id": role_id,
                            "name": role_name,
                        },
                        ensure_ascii=False,
                    ),
                )

                await send_log(
                    "role-added",
                    "➕ Role Added",
                    (
                        f"**User:** <@{after.id}>\n"
                        f"**Role:** "
                        f"{role.mention if role else role_name}\n"
                        f"**Role ID:** `{role_id}`"
                    ),
                )

                print(
                    f"[ROLE ADD] "
                    f"{after.id} <- {role_name}"
                )


            for role_id in removed:

                role = before.guild.get_role(role_id)

                role_name = (
                    role.name
                    if role
                    else "Unknown Role"
                )

                await member_event(
                    after.id,
                    "role_removed",
                    json.dumps(
                        {
                            "id": role_id,
                            "name": role_name,
                        },
                        ensure_ascii=False,
                    ),
                    None,
                )

                await send_log(
                    "role-removed",
                    "➖ Role Removed",
                    (
                        f"**User:** <@{after.id}>\n"
                        f"**Role:** "
                        f"{role.mention if role else role_name}\n"
                        f"**Role ID:** `{role_id}`"
                    ),
                )

                print(
                    f"[ROLE REMOVE] "
                    f"{after.id} -> {role_name}"
                )


            # ------------------------------------------------
            # TIMEOUT
            # ------------------------------------------------

            if (
                before.timed_out_until
                != after.timed_out_until
            ):

                old_timeout = (
                    before.timed_out_until.isoformat()
                    if before.timed_out_until
                    else None
                )

                new_timeout = (
                    after.timed_out_until.isoformat()
                    if after.timed_out_until
                    else None
                )

                await member_event(
                    after.id,
                    "timeout_change",
                    old_timeout,
                    new_timeout,
                )

                if after.timed_out_until:

                    unix = int(
                        after.timed_out_until.timestamp()
                    )

                    status = (
                        f"Timeout until "
                        f"<t:{unix}:F> "
                        f"(<t:{unix}:R>)"
                    )

                else:
                    status = "Timeout removed"

                await send_log(
                    "member-timeouts",
                    "⏳ Member Timeout Changed",
                    (
                        f"**User:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"**Status:** {status}"
                    ),
                )

                print(
                    f"[TIMEOUT] {after.id}: "
                    f"{old_timeout} -> {new_timeout}"
                )


            # ------------------------------------------------
            # GENERAL MEMBER UPDATE
            # ------------------------------------------------

            changes = []

            if before.nick != after.nick:
                changes.append("nickname")

            if before_roles != after_roles:
                changes.append("roles")

            if (
                before.timed_out_until
                != after.timed_out_until
            ):
                changes.append("timeout")

            if changes:

                await send_log(
                    "member-updates",
                    "👤 Member Updated",
                    (
                        f"**User:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"**Changed:** "
                        f"`{', '.join(changes)}`"
                    ),
                )

        except Exception as e:

            print(
                f"[MEMBER UPDATE ERROR] "
                f"{type(e).__name__}: {e}"
            )

            await send_log(
                "logger-errors",
                "⚠️ Member Update Error",
                (
                    f"**User ID:** `{after.id}`\n"
                    f"**Error:** "
                    f"`{type(e).__name__}: {e}`"
                ),
            )


    # ========================================================
    # USER PROFILE UPDATE
    # ========================================================

    @client.listen()
    async def on_user_update(before, after):

        try:

            guild = client.get_guild(
                source_guild_id
            )

            if guild is None:
                return

            member = guild.get_member(after.id)

            # User isn't a member of Source Guild
            if member is None:
                return


            # ------------------------------------------------
            # USERNAME
            # ------------------------------------------------

            if before.name != after.name:

                await member_event(
                    after.id,
                    "username_change",
                    before.name,
                    after.name,
                )

                await send_log(
                    "username-changes",
                    "👤 Username Changed",
                    (
                        f"**User ID:** `{after.id}`\n"
                        f"**Before:** `{before.name}`\n"
                        f"**After:** `{after.name}`"
                    ),
                )

                print(
                    f"[USERNAME] {after.id}: "
                    f"{before.name} -> {after.name}"
                )


            # ------------------------------------------------
            # GLOBAL DISPLAY NAME
            # ------------------------------------------------

            if (
                before.global_name
                != after.global_name
            ):

                await member_event(
                    after.id,
                    "global_name_change",
                    before.global_name,
                    after.global_name,
                )

                await send_log(
                    "member-updates",
                    "🪪 Display Name Changed",
                    (
                        f"**User ID:** `{after.id}`\n"
                        f"**Before:** "
                        f"`{before.global_name or 'None'}`\n"
                        f"**After:** "
                        f"`{after.global_name or 'None'}`"
                    ),
                )


            # ------------------------------------------------
            # AVATAR
            # ------------------------------------------------

            before_avatar = (
                str(before.avatar.url)
                if before.avatar
                else None
            )

            after_avatar = (
                str(after.avatar.url)
                if after.avatar
                else None
            )

            if before_avatar != after_avatar:

                await member_event(
                    after.id,
                    "avatar_change",
                    before_avatar,
                    after_avatar,
                )

                await send_log(
                    "avatar-changes",
                    "🖼️ Avatar Changed",
                    (
                        f"**User:** {after.mention}\n"
                        f"**User ID:** `{after.id}`\n"
                        f"Avatar was changed."
                    ),
                )

                print(
                    f"[AVATAR] {after.id}"
                )

        except Exception as e:

            print(
                f"[USER UPDATE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # REACTION ADD
    # ========================================================

    @client.listen()
    async def on_raw_reaction_add(payload):

        if payload.guild_id != source_guild_id:
            return

        # Ignore bot's own reactions
        if (
            client.user
            and payload.user_id == client.user.id
        ):
            return

        try:

            await reaction_event(
                payload.message_id,
                payload.channel_id,
                payload.user_id,
                payload.emoji,
                "add",
            )

            await send_log(
                "reactions-added",
                "➕ Reaction Added",
                (
                    f"**User:** <@{payload.user_id}> "
                    f"(`{payload.user_id}`)\n"
                    f"**Channel:** "
                    f"<#{payload.channel_id}>\n"
                    f"**Message ID:** "
                    f"`{payload.message_id}`\n"
                    f"**Emoji:** `{payload.emoji}`"
                ),
            )

            print(
                f"[REACTION ADD] "
                f"{payload.user_id} "
                f"{payload.emoji} "
                f"-> {payload.message_id}"
            )

        except Exception as e:

            print(
                f"[REACTION ADD ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # REACTION REMOVE
    # ========================================================

    @client.listen()
    async def on_raw_reaction_remove(payload):

        if payload.guild_id != source_guild_id:
            return

        try:

            await reaction_event(
                payload.message_id,
                payload.channel_id,
                payload.user_id,
                payload.emoji,
                "remove",
            )

            await send_log(
                "reactions-removed",
                "➖ Reaction Removed",
                (
                    f"**User:** <@{payload.user_id}> "
                    f"(`{payload.user_id}`)\n"
                    f"**Channel:** "
                    f"<#{payload.channel_id}>\n"
                    f"**Message ID:** "
                    f"`{payload.message_id}`\n"
                    f"**Emoji:** `{payload.emoji}`"
                ),
            )

            print(
                f"[REACTION REMOVE] "
                f"{payload.user_id} "
                f"{payload.emoji} "
                f"-> {payload.message_id}"
            )

        except Exception as e:

            print(
                f"[REACTION REMOVE ERROR] "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # ALL REACTIONS CLEARED
    # ========================================================

    @client.listen()
    async def on_raw_reaction_clear(payload):

        if payload.guild_id != source_guild_id:
            return

        try:

            await reaction_event(
                payload.message_id,
                payload.channel_id,
                None,
                "*",
                "clear_all",
            )

            await send_log(
                "reactions-cleared",
                "🧹 Reactions Cleared",
                (
                    f"**Channel:** "
                    f"<#{payload.channel_id}>\n"
                    f"**Message ID:** "
                    f"`{payload.message_id}`\n"
                    f"All reactions were removed."
                ),
            )

            print(
                f"[REACTIONS CLEAR] "
                f"{payload.message_id}"
            )

        except Exception as e:

            print(
                f"[REACTIONS CLEAR ERROR] "
                f"{type(e).__name__}: {e}"
            )
