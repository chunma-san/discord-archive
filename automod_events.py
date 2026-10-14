import json
from datetime import datetime, timezone

import aiosqlite
from database import connect_db


def setup_automod_events(
    client,
    source_guild_id,
    db_path,
    send_log,
):
    def utc_now():
        return datetime.now(timezone.utc).isoformat()


    def safe(value):
        if value is None:
            return None

        try:
            return str(value)
        except Exception:
            return repr(value)


    async def save_event(
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


    def rule_data(rule):
        return {
            "id": rule.id,
            "name": rule.name,
            "enabled": rule.enabled,
            "creator_id": getattr(rule, "creator_id", None),
            "event_type": safe(
                getattr(rule, "event_type", None)
            ),
            "trigger": safe(
                getattr(rule, "trigger", None)
            ),
            "actions": [
                safe(action)
                for action in getattr(rule, "actions", [])
            ],
            "exempt_roles": [
                getattr(role, "id", role)
                for role in getattr(rule, "exempt_roles", [])
            ],
            "exempt_channels": [
                getattr(channel, "id", channel)
                for channel in getattr(
                    rule,
                    "exempt_channels",
                    [],
                )
            ],
        }


    @client.listen("on_automod_rule_create")
    async def automod_rule_create(rule):
        if rule.guild.id != source_guild_id:
            return

        try:
            data = rule_data(rule)

            await save_event(
                "automod_rule_create",
                target_id=rule.id,
                actor_id=getattr(
                    rule,
                    "creator_id",
                    None,
                ),
                data=data,
            )

            await send_log(
                "automod-events",
                "🛡️ AutoMod Rule Created",
                (
                    f"**Rule:** `{rule.name}`\n"
                    f"**Rule ID:** `{rule.id}`\n"
                    f"**Enabled:** `{rule.enabled}`\n"
                    f"**Creator ID:** "
                    f"`{getattr(rule, 'creator_id', None)}`\n"
                    f"**Trigger:** "
                    f"`{safe(getattr(rule, 'trigger', None))}`\n"
                    f"**Actions:** "
                    f"`{len(getattr(rule, 'actions', []))}`"
                ),
            )

            print(
                f"[AUTOMOD CREATE] "
                f"{rule.name} ({rule.id})"
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ AutoMod Create Error",
                f"`{type(e).__name__}: {e}`",
            )


    @client.listen("on_automod_rule_update")
    async def automod_rule_update(rule):
        if rule.guild.id != source_guild_id:
            return

        try:
            data = rule_data(rule)

            await save_event(
                "automod_rule_update",
                target_id=rule.id,
                actor_id=getattr(
                    rule,
                    "creator_id",
                    None,
                ),
                data=data,
            )

            await send_log(
                "automod-events",
                "🛡️ AutoMod Rule Updated",
                (
                    f"**Rule:** `{rule.name}`\n"
                    f"**Rule ID:** `{rule.id}`\n"
                    f"**Enabled:** `{rule.enabled}`\n"
                    f"**Trigger:** "
                    f"`{safe(getattr(rule, 'trigger', None))}`\n"
                    f"**Actions:** "
                    f"`{len(getattr(rule, 'actions', []))}`"
                ),
            )

            print(
                f"[AUTOMOD UPDATE] "
                f"{rule.name} ({rule.id})"
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ AutoMod Update Error",
                f"`{type(e).__name__}: {e}`",
            )


    @client.listen("on_automod_rule_delete")
    async def automod_rule_delete(rule):
        if rule.guild.id != source_guild_id:
            return

        try:
            await save_event(
                "automod_rule_delete",
                target_id=rule.id,
                actor_id=getattr(
                    rule,
                    "creator_id",
                    None,
                ),
                data=rule_data(rule),
            )

            await send_log(
                "automod-events",
                "🗑️ AutoMod Rule Deleted",
                (
                    f"**Rule:** `{rule.name}`\n"
                    f"**Rule ID:** `{rule.id}`\n"
                    f"**Creator ID:** "
                    f"`{getattr(rule, 'creator_id', None)}`"
                ),
            )

            print(
                f"[AUTOMOD DELETE] "
                f"{rule.name} ({rule.id})"
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ AutoMod Delete Error",
                f"`{type(e).__name__}: {e}`",
            )


    @client.listen("on_automod_action")
    async def automod_action(execution):
        guild = execution.guild

        if guild is None or guild.id != source_guild_id:
            return

        try:
            member = getattr(execution, "member", None)
            user_id = (
                member.id
                if member
                else getattr(execution, "user_id", None)
            )

            channel = getattr(
                execution,
                "channel",
                None,
            )

            channel_id = (
                channel.id
                if channel
                else getattr(
                    execution,
                    "channel_id",
                    None,
                )
            )

            rule_id = getattr(
                execution,
                "rule_id",
                None,
            )

            action = getattr(
                execution,
                "action",
                None,
            )

            message_id = getattr(
                execution,
                "message_id",
                None,
            )

            content = getattr(
                execution,
                "content",
                None,
            )

            matched_keyword = getattr(
                execution,
                "matched_keyword",
                None,
            )

            matched_content = getattr(
                execution,
                "matched_content",
                None,
            )

            data = {
                "rule_id": rule_id,
                "user_id": user_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "action": safe(action),
                "content": content,
                "matched_keyword": matched_keyword,
                "matched_content": matched_content,
            }

            await save_event(
                "automod_action",
                target_id=user_id,
                data=data,
            )

            await send_log(
                "automod-events",
                "🚨 AutoMod Action Executed",
                (
                    f"**User ID:** `{user_id}`\n"
                    f"**Rule ID:** `{rule_id}`\n"
                    f"**Channel ID:** `{channel_id}`\n"
                    f"**Message ID:** `{message_id}`\n"
                    f"**Action:** `{safe(action)}`\n"
                    f"**Matched Keyword:** "
                    f"`{matched_keyword or 'None'}`\n"
                    f"**Matched Content:** "
                    f"`{matched_content or 'None'}`"
                ),
            )

            print(
                f"[AUTOMOD ACTION] "
                f"user={user_id} rule={rule_id}"
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ AutoMod Action Error",
                f"`{type(e).__name__}: {e}`",
            )
