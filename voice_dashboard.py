import asyncio
from datetime import datetime, timezone

import discord
from log_labels import channel_link


def setup_voice_dashboard(
    client,
    source_guild_id,
    archive_guild_id,
):
    dashboard_task = None

    async def get_dashboard_channel():
        guild = client.get_guild(archive_guild_id)

        if guild is None:
            return None

        channel = discord.utils.get(
            guild.text_channels,
            name="voice-dashboard",
        )

        if channel:
            return channel

        category = discord.utils.get(
            guild.categories,
            name="10・SEARCH",
        )

        try:
            channel = await guild.create_text_channel(
                "voice-dashboard",
                category=category,
                overwrites=(
                    category.overwrites
                    if category
                    else {
                        guild.default_role:
                            discord.PermissionOverwrite(
                                view_channel=False,
                            )
                    }
                ),
                topic=(
                    "Live Voice dashboard for the "
                    "Source Guild."
                ),
            )

            print(
                "[VOICE DASHBOARD] "
                "Created #voice-dashboard"
            )

            return channel

        except Exception as e:
            print(
                "[VOICE DASHBOARD ERROR] "
                f"Cannot create channel: {e}"
            )
            return None

    def build_embed():
        guild = client.get_guild(source_guild_id)

        if guild is None:
            return None

        embed = discord.Embed(
            title="🎙️ Source Guild LIVE VOICE",
            description=(
                "Live voice-state overview.\n"
                "Big Brain is **not connected to voice**."
            ),
            timestamp=datetime.now(timezone.utc),
        )

        active_channels = []

        for channel in (
            list(guild.voice_channels)
            + list(guild.stage_channels)
        ):
            members = [
                member
                for member in channel.members
                if not member.bot
            ]

            if not members:
                continue

            active_channels.append(
                (channel, members)
            )

        total_users = sum(
            len(members)
            for _, members in active_channels
        )

        if not active_channels:
            embed.add_field(
                name="🔇 No active voice channels",
                value="Nobody is currently in voice.",
                inline=False,
            )

        else:
            for channel, members in active_channels:
                lines = []

                for member in members[:30]:
                    state = member.voice
                    flags = []

                    if state:
                        if state.self_mute:
                            flags.append("🔇")

                        if state.self_deaf:
                            flags.append("🎧")

                        if state.self_stream:
                            flags.append("📺")

                        if state.self_video:
                            flags.append("📹")

                    suffix = (
                        " " + " ".join(flags)
                        if flags
                        else ""
                    )

                    lines.append(
                        f"• {member.mention}{suffix}"
                    )

                if len(members) > 30:
                    lines.append(
                        f"• +{len(members) - 30} more"
                    )

                value = "\n".join(lines)

                if len(value) > 1000:
                    value = value[:997] + "..."

                embed.add_field(
                    name=(
                        f"🔊 {channel.name} "
                        f"— {len(members)}"
                    ),
                    value=(
                        f"{channel_link(channel)}\n{value}"
                    )[:1024],
                    inline=False,
                )

        embed.set_footer(
            text=(
                f"Total users in voice: {total_users} "
                "• Auto refresh"
            )
        )

        return embed

    async def find_dashboard_message(channel):
        try:
            async for message in channel.history(
                limit=20
            ):
                if (
                    message.author.id == client.user.id
                    and message.embeds
                    and message.embeds[0].title
                    == "🎙️ Source Guild LIVE VOICE"
                ):
                    return message

        except Exception as e:
            print(
                "[VOICE DASHBOARD ERROR] "
                f"History: {e}"
            )

        return None

    async def dashboard_worker():
        await client.wait_until_ready()

        await asyncio.sleep(5)

        channel = await get_dashboard_channel()

        if channel is None:
            return

        dashboard_message = (
            await find_dashboard_message(channel)
        )

        while not client.is_closed():
            try:
                embed = build_embed()

                if embed is None:
                    await asyncio.sleep(30)
                    continue

                if dashboard_message is None:
                    dashboard_message = (
                        await channel.send(
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    )

                    print(
                        "[VOICE DASHBOARD] "
                        "Dashboard message created."
                    )

                else:
                    await dashboard_message.edit(
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

                await asyncio.sleep(30)

            except discord.NotFound:
                dashboard_message = None
                await asyncio.sleep(5)

            except Exception as e:
                print(
                    "[VOICE DASHBOARD ERROR] "
                    f"{type(e).__name__}: {e}"
                )
                await asyncio.sleep(30)

    @client.listen()
    async def on_ready():
        nonlocal dashboard_task

        if (
            dashboard_task is None
            or dashboard_task.done()
        ):
            dashboard_task = asyncio.create_task(
                dashboard_worker()
            )
