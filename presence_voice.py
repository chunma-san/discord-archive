from datetime import datetime, timezone
import json

import aiosqlite
from database import connect_db


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def activity_list(member):
    result = []

    for activity in member.activities:
        try:
            item = {
                "type": str(activity.type),
                "name": getattr(activity, "name", None),
                "details": getattr(activity, "details", None),
                "state": getattr(activity, "state", None),
            }

            result.append(item)

        except Exception:
            continue

    return result


def activity_string(member):
    return json.dumps(
        activity_list(member),
        ensure_ascii=False,
        sort_keys=True,
    )


def setup_presence_voice(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    # Tracks active voice sessions
    voice_sessions = {}


    # ========================================================
    # DATABASE HELPERS
    # ========================================================

    async def save_presence(
        user_id,
        old_status,
        new_status,
        old_activity,
        new_activity,
    ):
        async with connect_db(db_path) as db:

            await db.execute(
                """
                INSERT INTO presence_events (
                    guild_id,
                    user_id,
                    old_status,
                    new_status,
                    old_activity,
                    new_activity,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_guild_id,
                    user_id,
                    old_status,
                    new_status,
                    old_activity,
                    new_activity,
                    utc_now(),
                ),
            )

            await db.commit()


    async def save_voice(
        user_id,
        event_type,
        before,
        after,
    ):
        async with connect_db(db_path) as db:

            await db.execute(
                """
                INSERT INTO voice_events (
                    guild_id,
                    user_id,
                    event_type,
                    old_channel_id,
                    new_channel_id,
                    self_mute,
                    self_deaf,
                    server_mute,
                    server_deaf,
                    self_stream,
                    self_video,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_guild_id,
                    user_id,
                    event_type,

                    (
                        before.channel.id
                        if before.channel
                        else None
                    ),

                    (
                        after.channel.id
                        if after.channel
                        else None
                    ),

                    int(after.self_mute),
                    int(after.self_deaf),
                    int(after.mute),
                    int(after.deaf),
                    int(after.self_stream),
                    int(after.self_video),

                    utc_now(),
                ),
            )

            await db.commit()


    async def set_voice_session(
        user_id,
        channel_id,
        started_at=None,
    ):
        timestamp = started_at or utc_now()

        async with connect_db(db_path) as db:
            await db.execute(
                """
                INSERT INTO voice_sessions (
                    user_id,
                    guild_id,
                    channel_id,
                    started_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    channel_id = excluded.channel_id,
                    started_at = excluded.started_at,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    source_guild_id,
                    channel_id,
                    timestamp,
                    utc_now(),
                ),
            )
            await db.commit()


    async def update_voice_session_channel(
        user_id,
        channel_id,
    ):
        async with connect_db(db_path) as db:
            await db.execute(
                """
                UPDATE voice_sessions
                SET channel_id = ?,
                    updated_at = ?
                WHERE user_id = ?
                  AND guild_id = ?
                """,
                (
                    channel_id,
                    utc_now(),
                    user_id,
                    source_guild_id,
                ),
            )
            await db.commit()


    async def get_voice_session(user_id):
        async with connect_db(db_path) as db:
            async with db.execute(
                """
                SELECT
                    channel_id,
                    started_at,
                    updated_at
                FROM voice_sessions
                WHERE user_id = ?
                  AND guild_id = ?
                """,
                (
                    user_id,
                    source_guild_id,
                ),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "channel_id": row[0],
            "started_at": row[1],
            "updated_at": row[2],
        }


    async def save_voice_session_history(
        user_id,
        channel_id,
        started_at,
        ended_at=None,
    ):
        ended_at = ended_at or datetime.now(timezone.utc)

        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        if isinstance(ended_at, str):
            ended_at = datetime.fromisoformat(ended_at)

        seconds = max(
            0,
            int((ended_at - started_at).total_seconds()),
        )

        async with connect_db(db_path) as db:
            await db.execute(
                """
                INSERT INTO voice_session_history (
                    guild_id,
                    user_id,
                    channel_id,
                    started_at,
                    ended_at,
                    duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_guild_id,
                    user_id,
                    channel_id,
                    started_at.isoformat(),
                    ended_at.isoformat(),
                    seconds,
                ),
            )
            await db.commit()

        return seconds


    async def delete_voice_session(user_id):
        async with connect_db(db_path) as db:
            await db.execute(
                """
                DELETE FROM voice_sessions
                WHERE user_id = ?
                  AND guild_id = ?
                """,
                (
                    user_id,
                    source_guild_id,
                ),
            )
            await db.commit()


    async def reconcile_voice_sessions():
        guild = client.get_guild(source_guild_id)

        if guild is None:
            print("[VOICE SESSION] Source guild not found.")
            return

        active = {}

        for channel in guild.voice_channels:
            for member in channel.members:
                active[member.id] = channel.id

        for channel in guild.stage_channels:
            for member in channel.members:
                active[member.id] = channel.id

        async with connect_db(db_path) as db:
            async with db.execute(
                """
                SELECT user_id, channel_id, started_at
                FROM voice_sessions
                WHERE guild_id = ?
                """,
                (source_guild_id,),
            ) as cursor:
                stored = await cursor.fetchall()

            stored_by_user = {
                row[0]: {
                    "channel_id": row[1],
                    "started_at": row[2],
                }
                for row in stored
            }

            # Remove stale DB sessions for users no longer in voice.
            for user_id in stored_by_user:
                if user_id not in active:
                    await db.execute(
                        """
                        DELETE FROM voice_sessions
                        WHERE user_id = ?
                          AND guild_id = ?
                        """,
                        (
                            user_id,
                            source_guild_id,
                        ),
                    )

            # Preserve existing start time for sessions that survived
            # the restart; create a new start only when the bot first
            # discovers a currently-active voice user.
            for user_id, channel_id in active.items():
                existing = stored_by_user.get(user_id)

                if existing:
                    started_at = existing["started_at"]

                    await db.execute(
                        """
                        UPDATE voice_sessions
                        SET channel_id = ?,
                            updated_at = ?
                        WHERE user_id = ?
                          AND guild_id = ?
                        """,
                        (
                            channel_id,
                            utc_now(),
                            user_id,
                            source_guild_id,
                        ),
                    )
                else:
                    started_at = utc_now()

                    await db.execute(
                        """
                        INSERT INTO voice_sessions (
                            user_id,
                            guild_id,
                            channel_id,
                            started_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            source_guild_id,
                            channel_id,
                            started_at,
                            utc_now(),
                        ),
                    )

                try:
                    parsed = datetime.fromisoformat(started_at)
                except Exception:
                    parsed = datetime.now(timezone.utc)

                voice_sessions[user_id] = {
                    "channel_id": channel_id,
                    "started_at": parsed,
                }

            await db.commit()

        print(
            f"[VOICE SESSION] Reconciled "
            f"{len(active)} active session(s)."
        )


    # ========================================================
    # PRESENCE
    # ========================================================

    @client.listen()
    async def on_presence_update(before, after):

        if after.guild.id != source_guild_id:
            return

        try:
            old_status = str(before.status)
            new_status = str(after.status)

            old_activity = activity_string(before)
            new_activity = activity_string(after)

            status_changed = (
                old_status != new_status
            )

            activity_changed = (
                old_activity != new_activity
            )

            if not status_changed and not activity_changed:
                return

            await save_presence(
                after.id,
                old_status,
                new_status,
                old_activity,
                new_activity,
            )


            # ------------------------------------------------
            # STATUS
            # ------------------------------------------------

            if status_changed:

                await send_log(
                    "status-changes",
                    "🟢 Presence Changed",
                    (
                        f"**User:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"**Before:** `{old_status}`\n"
                        f"**After:** `{new_status}`"
                    ),
                )

                # Separate online/offline events
                if (
                    old_status == "offline"
                    or new_status == "offline"
                ):
                    await send_log(
                        "online-offline",
                        "🔌 Online / Offline",
                        (
                            f"**User:** {after.mention} "
                            f"(`{after.id}`)\n"
                            f"`{old_status}` → "
                            f"`{new_status}`"
                        ),
                    )

                print(
                    f"[PRESENCE] {after.id}: "
                    f"{old_status} -> {new_status}"
                )


            # ------------------------------------------------
            # ACTIVITIES
            # ------------------------------------------------

            if activity_changed:

                old_names = [
                    x.get("name")
                    for x in activity_list(before)
                    if x.get("name")
                ]

                new_names = [
                    x.get("name")
                    for x in activity_list(after)
                    if x.get("name")
                ]

                await send_log(
                    "activity-changes",
                    "🎮 Activity Changed",
                    (
                        f"**User:** {after.mention} "
                        f"(`{after.id}`)\n"
                        f"**Before:** "
                        f"`{', '.join(old_names) if old_names else 'None'}`\n"
                        f"**After:** "
                        f"`{', '.join(new_names) if new_names else 'None'}`"
                    ),
                )

                print(
                    f"[ACTIVITY] {after.id}: "
                    f"{old_names} -> {new_names}"
                )

        except Exception as e:

            print(
                f"[PRESENCE ERROR] "
                f"{type(e).__name__}: {e}"
            )

            await send_log(
                "logger-errors",
                "⚠️ Presence Error",
                (
                    f"**User ID:** `{after.id}`\n"
                    f"**Error:** "
                    f"`{type(e).__name__}: {e}`"
                ),
            )



    voice_reconciled = False

    @client.listen()
    async def on_ready():
        nonlocal voice_reconciled

        if voice_reconciled:
            return

        try:
            await reconcile_voice_sessions()
            voice_reconciled = True

        except Exception as e:
            print(
                f"[VOICE SESSION ERROR] "
                f"{type(e).__name__}: {e}"
            )

            await send_log(
                "logger-errors",
                "⚠️ Voice Session Recovery Error",
                (
                    f"**Error:** "
                    f"`{type(e).__name__}: {e}`"
                ),
            )


    # ========================================================
    # VOICE
    # ========================================================

    @client.listen()
    async def on_voice_state_update(
        member,
        before,
        after,
    ):

        if member.guild.id != source_guild_id:
            return

        try:
            before_channel = before.channel
            after_channel = after.channel


            # ------------------------------------------------
            # JOIN
            # ------------------------------------------------

            if (
                before_channel is None
                and after_channel is not None
            ):
                await save_voice(
                    member.id,
                    "join",
                    before,
                    after,
                )

                started_at = datetime.now(timezone.utc)

                voice_sessions[member.id] = {
                    "channel_id": after_channel.id,
                    "started_at": started_at,
                }

                await set_voice_session(
                    member.id,
                    after_channel.id,
                    started_at.isoformat(),
                )

                await send_log(
                    "voice-join",
                    "🔊 Voice Joined",
                    (
                        f"**User:** {member.mention} "
                        f"(`{member.id}`)\n"
                        f"**Channel:** "
                        f"{after_channel.mention} "
                        f"(`{after_channel.id}`)"
                    ),
                )

                print(
                    f"[VOICE JOIN] "
                    f"{member} -> "
                    f"{after_channel.name}"
                )


            # ------------------------------------------------
            # LEAVE
            # ------------------------------------------------

            elif (
                before_channel is not None
                and after_channel is None
            ):
                await save_voice(
                    member.id,
                    "leave",
                    before,
                    after,
                )

                session = voice_sessions.pop(
                    member.id,
                    None,
                )

                if session is None:
                    stored_session = await get_voice_session(
                        member.id
                    )

                    if stored_session:
                        try:
                            started_at = datetime.fromisoformat(
                                stored_session["started_at"]
                            )

                            session = {
                                "channel_id": (
                                    stored_session["channel_id"]
                                ),
                                "started_at": started_at,
                            }

                        except Exception:
                            session = None

                duration_text = "Unknown"

                if session:

                    seconds = max(
                        0,
                        int(
                            (
                                datetime.now(timezone.utc)
                                - session["started_at"]
                            ).total_seconds()
                        ),
                    )

                    hours, remainder = divmod(
                        seconds,
                        3600,
                    )

                    minutes, seconds = divmod(
                        remainder,
                        60,
                    )

                    duration_text = (
                        f"{hours:02d}:"
                        f"{minutes:02d}:"
                        f"{seconds:02d}"
                    )

                if session:
                    await save_voice_session_history(
                        member.id,
                        session["channel_id"],
                        session["started_at"],
                    )

                await delete_voice_session(member.id)

                await send_log(
                    "voice-leave",
                    "🔇 Voice Left",
                    (
                        f"**User:** {member.mention} "
                        f"(`{member.id}`)\n"
                        f"**Channel:** "
                        f"{before_channel.name} "
                        f"(`{before_channel.id}`)\n"
                        f"**Session:** `{duration_text}`"
                    ),
                )

                await send_log(
                    "voice-sessions",
                    "⏱️ Voice Session Ended",
                    (
                        f"**User:** {member.mention} "
                        f"(`{member.id}`)\n"
                        f"**Channel:** "
                        f"`{before_channel.name}`\n"
                        f"**Duration:** "
                        f"`{duration_text}`"
                    ),
                )

                print(
                    f"[VOICE LEAVE] "
                    f"{member} <- "
                    f"{before_channel.name} "
                    f"({duration_text})"
                )


            # ------------------------------------------------
            # MOVE
            # ------------------------------------------------

            elif (
                before_channel is not None
                and after_channel is not None
                and before_channel.id
                != after_channel.id
            ):
                await save_voice(
                    member.id,
                    "move",
                    before,
                    after,
                )

                session = voice_sessions.get(
                    member.id
                )

                stored_session = await get_voice_session(
                    member.id
                )

                # Prefer the persistent DB session because it
                # survives Big Brain restarts.
                if stored_session:
                    segment_started = datetime.fromisoformat(
                        stored_session["started_at"]
                    )

                    old_channel_id = (
                        stored_session["channel_id"]
                        or before_channel.id
                    )

                elif session:
                    segment_started = session["started_at"]
                    old_channel_id = (
                        session["channel_id"]
                        or before_channel.id
                    )

                else:
                    # Recovery fallback: Discord reported MOVE
                    # without a known active session.
                    segment_started = datetime.now(timezone.utc)
                    old_channel_id = before_channel.id

                moved_at = datetime.now(timezone.utc)

                await save_voice_session_history(
                    member.id,
                    old_channel_id,
                    segment_started,
                    moved_at,
                )

                # A MOVE ends the old channel segment and starts
                # a fresh segment in the destination channel.
                voice_sessions[member.id] = {
                    "channel_id": after_channel.id,
                    "started_at": moved_at,
                }

                await set_voice_session(
                    member.id,
                    after_channel.id,
                    moved_at.isoformat(),
                )

                await send_log(
                    "voice-move",
                    "↔️ Voice Channel Changed",
                    (
                        f"**User:** {member.mention} "
                        f"(`{member.id}`)\n"
                        f"**From:** "
                        f"{before_channel.mention}\n"
                        f"**To:** "
                        f"{after_channel.mention}"
                    ),
                )

                print(
                    f"[VOICE MOVE] {member}: "
                    f"{before_channel.name} -> "
                    f"{after_channel.name}"
                )


            # ------------------------------------------------
            # SELF MUTE / DEAF
            # ------------------------------------------------

            state_changes = []

            if before.self_mute != after.self_mute:
                state_changes.append(
                    f"Self Mute: "
                    f"`{before.self_mute}` → "
                    f"`{after.self_mute}`"
                )

            if before.self_deaf != after.self_deaf:
                state_changes.append(
                    f"Self Deaf: "
                    f"`{before.self_deaf}` → "
                    f"`{after.self_deaf}`"
                )

            if before.mute != after.mute:
                state_changes.append(
                    f"Server Mute: "
                    f"`{before.mute}` → "
                    f"`{after.mute}`"
                )

            if before.deaf != after.deaf:
                state_changes.append(
                    f"Server Deaf: "
                    f"`{before.deaf}` → "
                    f"`{after.deaf}`"
                )

            if state_changes:

                await save_voice(
                    member.id,
                    "mute_deafen_change",
                    before,
                    after,
                )

                await send_log(
                    "mute-deafen",
                    "🎙️ Voice State Changed",
                    (
                        f"**User:** {member.mention} "
                        f"(`{member.id}`)\n"
                        + "\n".join(state_changes)
                    ),
                )

                print(
                    f"[VOICE STATE] "
                    f"{member.id}: "
                    f"{' | '.join(state_changes)}"
                )


            # ------------------------------------------------
            # STREAM / VIDEO
            # ------------------------------------------------

            media_changes = []

            if (
                before.self_stream
                != after.self_stream
            ):
                media_changes.append(
                    f"Stream: "
                    f"`{before.self_stream}` → "
                    f"`{after.self_stream}`"
                )

            if (
                before.self_video
                != after.self_video
            ):
                media_changes.append(
                    f"Camera: "
                    f"`{before.self_video}` → "
                    f"`{after.self_video}`"
                )

            if media_changes:

                await save_voice(
                    member.id,
                    "stream_video_change",
                    before,
                    after,
                )

                await send_log(
                    "stream-video",
                    "📹 Stream / Camera Changed",
                    (
                        f"**User:** {member.mention} "
                        f"(`{member.id}`)\n"
                        + "\n".join(media_changes)
                    ),
                )

                print(
                    f"[VOICE MEDIA] "
                    f"{member.id}: "
                    f"{' | '.join(media_changes)}"
                )

        except Exception as e:

            print(
                f"[VOICE ERROR] "
                f"{type(e).__name__}: {e}"
            )

            await send_log(
                "logger-errors",
                "⚠️ Voice Error",
                (
                    f"**User ID:** `{member.id}`\n"
                    f"**Error:** "
                    f"`{type(e).__name__}: {e}`"
                ),
            )
