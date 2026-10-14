from datetime import datetime, timezone
import json

import aiosqlite
from database import connect_db
import discord
from log_labels import role_label


def now():
    return datetime.now(timezone.utc).isoformat()


def snapshot(role):
    return {
        "id": role.id,
        "name": role.name,
        "position": role.position,
        "permissions": role.permissions.value,
        "colour": role.colour.value,
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "managed": role.managed,
    }


def permission_changes(before, after):
    old_permissions = dict(before.permissions)
    new_permissions = dict(after.permissions)
    changes = []

    for name in sorted(set(old_permissions) | set(new_permissions)):
        old_value = old_permissions.get(name, False)
        new_value = new_permissions.get(name, False)
        if old_value != new_value:
            label = name.replace("_", " ").capitalize()
            changes.append(
                f"• **{label}:** "
                f"{'Allowed' if old_value else 'Denied'} → "
                f"{'Allowed' if new_value else 'Denied'}"
            )

    return changes


def enabled_permissions(permissions):
    names = [
        name.replace("_", " ").capitalize()
        for name, enabled in permissions
        if enabled
    ]
    return ", ".join(names) if names else "None"


def setup_role_events(
    client,
    source_guild_id,
    db_path,
    send_log,
):

    async def save(event, role_id, data, actor_id=None):

        async with connect_db(db_path) as db:

            await db.execute(
                """
                INSERT INTO server_events
                (
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
                    event,
                    role_id,
                    actor_id,
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        default=str,
                    ),
                    now(),
                ),
            )

            await db.commit()


    async def find_actor(role, action):
        try:
            now = datetime.now(timezone.utc)
            async for entry in role.guild.audit_logs(
                limit=10,
                action=action,
            ):
                target_id = getattr(entry.target, "id", None)
                age = (now - entry.created_at).total_seconds()
                if target_id == role.id and 0 <= age <= 30:
                    return entry.user
        except (discord.Forbidden, discord.HTTPException):
            pass
        except Exception as error:
            print(
                f"[ROLE AUDIT LOOKUP] "
                f"{type(error).__name__}: {error}"
            )
        return None


    @client.listen()
    async def on_guild_role_create(role):

        if role.guild.id != source_guild_id:
            return

        actor = await find_actor(
            role,
            discord.AuditLogAction.role_create,
        )

        await save(
            "role_create",
            role.id,
            snapshot(role),
            actor.id if actor else None,
        )

        await send_log(
            "role-created",
            "🆕 Role Created",
            (
                f"**Role:** {role_label(role)}\n"
                f"**Name:** `{role.name}`\n"
                f"**Created by:** "
                f"{actor.mention if actor else 'Not available in audit log'}\n"
                f"**Enabled permissions:** "
                f"{enabled_permissions(role.permissions)}"
            ),
        )

        print(
            f"[ROLE CREATE] "
            f"{role.name} ({role.id})"
        )


    @client.listen()
    async def on_guild_role_delete(role):

        if role.guild.id != source_guild_id:
            return

        actor = await find_actor(
            role,
            discord.AuditLogAction.role_delete,
        )

        await save(
            "role_delete",
            role.id,
            snapshot(role),
            actor.id if actor else None,
        )

        await send_log(
            "role-deleted",
            "🗑️ Role Deleted",
            (
                f"**Name:** `{role.name}`\n"
                f"**Deleted by:** "
                f"{actor.mention if actor else 'Not available in audit log'}\n"
                f"**Enabled permissions:** "
                f"{enabled_permissions(role.permissions)}"
            ),
        )

        print(
            f"[ROLE DELETE] "
            f"{role.name} ({role.id})"
        )


    @client.listen()
    async def on_guild_role_update(
        before,
        after,
    ):

        if after.guild.id != source_guild_id:
            return

        old = snapshot(before)
        new = snapshot(after)
        actor = await find_actor(
            after,
            discord.AuditLogAction.role_update,
        )

        changes = {}

        for key in old:
            if old[key] != new[key]:
                changes[key] = {
                    "before": old[key],
                    "after": new[key],
                }

        if not changes:
            return

        await save(
            "role_update",
            after.id,
            {
                "changes": changes,
            },
            actor.id if actor else None,
        )

        lines = []

        for key, value in changes.items():
            if key == "permissions":
                continue
            lines.append(
                f"**{key}:** "
                f"`{value['before']}` → "
                f"`{value['after']}`"
            )

        await send_log(
            "role-updated",
            "✏️ Role Updated",
            (
                f"**Role:** {role_label(after)}\n"
                f"**Changed by:** "
                f"{actor.mention if actor else 'Not available in audit log'}\n\n"
                + "\n".join(lines)[:3000]
            ),
        )

        if (
            before.permissions.value
            != after.permissions.value
        ):
            changed_permission_lines = permission_changes(
                before,
                after,
            )
            await send_log(
                "role-permissions",
                "🔐 Role Permissions Changed",
                (
                    f"**Role:** {role_label(after)}\n"
                    f"**Changed by:** "
                    f"{actor.mention if actor else 'Not available in audit log'}\n"
                    + (
                        "**Permission changes:**\n"
                        + "\n".join(changed_permission_lines)
                        if changed_permission_lines
                        else (
                            f"**Permissions before:** `{before.permissions.value}`\n"
                            f"**Permissions after:** `{after.permissions.value}`"
                        )
                    )
                ),
            )

        print(
            f"[ROLE UPDATE] "
            f"{after.name}: {list(changes)}"
        )
