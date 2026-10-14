import os
from datetime import datetime, timedelta, timezone

import discord
from log_labels import (
    channel_label,
    channel_link,
    normalize_source_references,
)


TRAP_CHANNEL_ID = int(os.getenv("TRAP_CHANNEL_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
TIMEOUT_DAYS = 7


def setup_security_trap(
    client,
    source_guild_id,
    archive_guild_id,
):
    async def archive_log(title, description):
        guild = client.get_guild(archive_guild_id)

        if guild is None:
            return

        channel = discord.utils.get(
            guild.text_channels,
            name="moderator-actions",
        )

        if channel is None:
            print(
                "[SECURITY TRAP WARNING] "
                "moderator-actions not found"
            )
            return

        source_guild = client.get_guild(source_guild_id)
        description = normalize_source_references(
            str(description),
            source_guild,
        )

        embed = discord.Embed(
            title=title,
            description=description[:4000],
            timestamp=datetime.now(timezone.utc),
        )

        try:
            await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as e:
            print(
                "[SECURITY TRAP LOG ERROR] "
                f"{type(e).__name__}: {e}"
            )

    async def dm_support(
        guild,
        member,
        timeout_result,
        delete_ok,
        content,
    ):
        role = guild.get_role(STAFF_ROLE_ID)

        if role is None:
            print(
                "[SECURITY TRAP ERROR] "
                f"Support role {STAFF_ROLE_ID} not found"
            )
            return 0, 0

        if not content:
            content = "[No text content]"

        content = content[:700]
        trap_channel = guild.get_channel(TRAP_CHANNEL_ID)
        trap_channel_link = channel_link(
            trap_channel,
            channel_id=TRAP_CHANNEL_ID,
            fallback_name="Try",
            guild_id=guild.id,
        )

        embed = discord.Embed(
            title="🚨 SECURITY TRAP TRIGGERED",
            description=(
                "An account triggered the security "
                f"honeypot in **{trap_channel_link}**.\n\n"
                f"**User:** {member.mention}\n"
                f"**Username:** `{member}`\n"
                "\n"
                f"**7-day timeout:** "
                f"`{timeout_result}`\n"
                f"**Message deleted:** "
                f"`{'YES' if delete_ok else 'FAILED'}`\n\n"
                "**Message:**\n"
                f"```text\n{content}\n```\n"
                "⚠️ The account may be compromised. "
                "Please investigate before removing "
                "the timeout."
            )[:4000],
            timestamp=datetime.now(timezone.utc),
        )

        sent = 0
        failed = 0

        for staff in role.members:
            if staff.bot:
                continue

            try:
                await staff.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                sent += 1

            except (
                discord.Forbidden,
                discord.HTTPException,
            ):
                failed += 1

        return sent, failed

    @client.listen()
    async def on_ready():
        guild = client.get_guild(source_guild_id)

        if guild is None:
            print(
                "[SECURITY TRAP ERROR] "
                "Source guild not found"
            )
            return

        channel = guild.get_channel(
            TRAP_CHANNEL_ID
        )

        if channel is None:
            print(
                "[SECURITY TRAP ERROR] "
                f"Channel {TRAP_CHANNEL_ID} not found"
            )
            return

        role = guild.get_role(STAFF_ROLE_ID)

        print(
            "[SECURITY TRAP] "
            f"Ready: #{channel.name} "
            f"({channel.id})"
        )

        if role:
            print(
                "[SECURITY TRAP] "
                f"Support role: {role.name} "
                f"({role.id})"
            )
        else:
            print(
                "[SECURITY TRAP WARNING] "
                f"Support role {STAFF_ROLE_ID} "
                "not found"
            )

    @client.listen()
    async def on_message(message):
        if message.guild is None:
            return

        if message.guild.id != source_guild_id:
            return

        if message.channel.id != TRAP_CHANNEL_ID:
            return

        # Never punish bots.
        if message.author.bot:
            return

        member = message.author

        print(
            "[SECURITY TRAP] "
            f"TRIGGERED: {member} ({member.id})"
        )

        content = (
            message.content
            or "[Attachment/embed/no text]"
        )

        delete_ok = False

        try:
            await message.delete()
            delete_ok = True
        except Exception as e:
            print(
                "[SECURITY TRAP DELETE ERROR] "
                f"{type(e).__name__}: {e}"
            )

        timeout_ok = False
        timeout_result = "Failed: no result"
        bot_member = message.guild.me

        if member.guild_permissions.administrator:
            timeout_result = "Skipped: target is a server administrator"
        elif bot_member is None:
            timeout_result = "Skipped: Big Brain member is unavailable"
        elif member.top_role >= bot_member.top_role:
            timeout_result = (
                "Skipped: target role is equal to or above Big Brain's top role"
            )
        elif not bot_member.guild_permissions.moderate_members:
            timeout_result = "Skipped: Big Brain lacks Moderate Members permission"
        else:
            try:
                timeout_until = (
                    datetime.now(timezone.utc)
                    + timedelta(days=TIMEOUT_DAYS)
                )

                await member.timeout(
                    timeout_until,
                    reason=(
                        "Security honeypot triggered "
                        "in #Try"
                    ),
                )

                timeout_ok = True
                timeout_result = (
                    f"Applied until {timeout_until.isoformat()}"
                )

            except Exception as e:
                timeout_result = (
                    f"Failed: {type(e).__name__}: {e}"
                )
                print(
                    "[SECURITY TRAP TIMEOUT ERROR] "
                    f"target={member} ({member.id}) "
                    f"{timeout_result}"
                )

        dm_sent, dm_failed = await dm_support(
            message.guild,
            member,
            timeout_result,
            delete_ok,
            content,
        )

        await archive_log(
            "🚨 Security Trap Triggered",
            (
                f"**User:** {member.mention}\n"
                f"**Username:** `{member}`\n"
                f"**Channel:** "
                f"{channel_label(message.channel)}\n\n"
                f"**7-day timeout:** "
                f"`{timeout_result}`\n"
                f"**Message deleted:** "
                f"`{'YES' if delete_ok else 'FAILED'}`\n"
                f"**Support DMs sent:** `{dm_sent}`\n"
                f"**Support DMs failed:** `{dm_failed}`\n\n"
                "⚠️ Possible compromised account. "
                "Manual review recommended."
            ),
        )

        print(
            "[SECURITY TRAP] "
            f"DONE user={member.id} "
            f"timeout={timeout_ok} "
            f"deleted={delete_ok} "
            f"dm_sent={dm_sent} "
            f"dm_failed={dm_failed}"
        )
