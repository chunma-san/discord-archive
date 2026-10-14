import os
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
ARCHIVE_GUILD_ID = int(os.getenv("ARCHIVE_GUILD_ID"))

STRUCTURE = {
    "00・SYSTEM": [
        "logger-status",
        "logger-errors",
        "logger-warnings",
        "bot-events",
    ],

    "01・MESSAGES": [
        "message-created",
        "message-deleted",
        "message-edited",
        "bulk-delete",
        "attachments",
        "embeds",
        "reactions-added",
        "reactions-removed",
        "reactions-cleared",
        "pins",
        "polls",
    ],

    "02・MEMBERS": [
        "member-join",
        "member-leave",
        "member-updates",
        "username-changes",
        "nickname-changes",
        "avatar-changes",
        "role-added",
        "role-removed",
        "member-timeouts",
    ],

    "03・PRESENCE": [
        "online-offline",
        "status-changes",
        "activity-changes",
    ],

    "04・VOICE": [
        "voice-join",
        "voice-leave",
        "voice-move",
        "mute-deafen",
        "stream-video",
        "voice-sessions",
    ],

    "05・MODERATION": [
        "bans",
        "unbans",
        "kicks",
        "timeouts",
        "messages-purged",
        "moderator-actions",
        "audit-log",
    ],

    "06・CHANNELS": [
        "channel-created",
        "channel-deleted",
        "channel-updated",
        "category-changes",
        "permission-changes",
        "threads-created",
        "threads-deleted",
        "threads-updated",
    ],

    "07・ROLES": [
        "role-created",
        "role-deleted",
        "role-updated",
        "role-permissions",
    ],

    "08・SERVER": [
        "server-updates",
        "emoji-changes",
        "sticker-changes",
        "invite-created",
        "invite-deleted",
        "webhook-changes",
        "stage-events",
        "scheduled-events",
        "automod-events",
        "miscellaneous",
    ],

    "09・DATABASE": [
        "database-status",
        "backup-status",
        "storage-status",
    ],

    "10・SEARCH": [
        "user-search",
        "message-search",
        "history-search",
    ],
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)


async def get_or_create_category(guild, name):
    category = discord.utils.get(guild.categories, name=name)

    if category:
        print(f"[=] Category exists: {name}")
        return category

    category = await guild.create_category(
        name,
        overwrites={
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
        },
        reason="Big Brain archive structure"
    )

    print(f"[+] Category created: {name}")
    return category


async def get_or_create_channel(guild, category, name):
    # Search inside this category only
    channel = discord.utils.get(
        category.text_channels,
        name=name
    )

    if channel:
        if not channel.permissions_synced:
            overwrites = dict(channel.overwrites)
            everyone = overwrites.get(
                guild.default_role,
                discord.PermissionOverwrite(),
            )
            everyone.view_channel = False
            overwrites[guild.default_role] = everyone
            await channel.edit(
                overwrites=overwrites,
                reason="Keep Big Brain archive logs private",
            )
        print(f"    [=] #{name}")
        return channel

    channel = await guild.create_text_channel(
        name,
        category=category,
        overwrites=category.overwrites,
        reason="Big Brain archive structure"
    )

    print(f"    [+] #{name}")
    return channel


@client.event
async def on_ready():
    print("=" * 60)
    print(f"Logged in as: {client.user}")
    print(f"Bot ID: {client.user.id}")
    print("=" * 60)

    guild = client.get_guild(ARCHIVE_GUILD_ID)

    if guild is None:
        print("ERROR: Archive Guild server not found.")
        await client.close()
        return

    print(f"Archive Guild: {guild.name}")
    print(f"ID: {guild.id}")
    print()
    print("Checking archive structure...")
    print()

    created_categories = 0
    created_channels = 0

    for category_name, channels in STRUCTURE.items():

        existing_category = discord.utils.get(
            guild.categories,
            name=category_name
        )

        if existing_category is None:
            created_categories += 1

        category = await get_or_create_category(
            guild,
            category_name
        )

        everyone = category.overwrites_for(guild.default_role)
        if everyone.view_channel is not False:
            overwrites = dict(category.overwrites)
            everyone.view_channel = False
            overwrites[guild.default_role] = everyone
            await category.edit(
                overwrites=overwrites,
                reason="Keep Big Brain archive logs private",
            )

        for channel_name in channels:

            existing_channel = discord.utils.get(
                category.text_channels,
                name=channel_name
            )

            if existing_channel is None:
                created_channels += 1

            await get_or_create_channel(
                guild,
                category,
                channel_name
            )

    # Also secure existing helper/orphan categories and channels that are not
    # in STRUCTURE so the archive server has no accidentally public rooms.
    for category in guild.categories:
        everyone = category.overwrites_for(guild.default_role)
        if everyone.view_channel is not False:
            overwrites = dict(category.overwrites)
            everyone.view_channel = False
            overwrites[guild.default_role] = everyone
            await category.edit(
                overwrites=overwrites,
                reason="Keep Big Brain archive logs private",
            )

    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
        if channel.category and channel.permissions_synced:
            continue
        everyone = channel.overwrites_for(guild.default_role)
        if everyone.view_channel is not False:
            overwrites = dict(channel.overwrites)
            everyone.view_channel = False
            overwrites[guild.default_role] = everyone
            await channel.edit(
                overwrites=overwrites,
                reason="Keep Big Brain archive logs private",
            )

    viewer_role_name = "Archive Viewer"
    viewer_role = discord.utils.get(
        guild.roles,
        name=viewer_role_name,
    )
    if viewer_role is None:
        viewer_role = await guild.create_role(
            name=viewer_role_name,
            permissions=discord.Permissions.none(),
            reason="Read-only access to all Big Brain archive rooms",
        )
        print(f"[+] Role created: {viewer_role_name}")
    elif viewer_role.permissions.value:
        raise RuntimeError(
            f"Role {viewer_role_name!r} already exists with server "
            "permissions; refusing to change its access unexpectedly."
        )

    viewer_overwrite = discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=False,
        send_messages_in_threads=False,
        add_reactions=False,
        create_public_threads=False,
        create_private_threads=False,
        connect=False,
        speak=False,
    )
    viewer_targets = [
        *guild.categories,
        *[
            channel
            for channel in guild.channels
            if not isinstance(channel, discord.CategoryChannel)
        ],
    ]
    viewer_overwrites_updated = 0
    for target in viewer_targets:
        if target.overwrites_for(viewer_role) == viewer_overwrite:
            continue
        await target.set_permissions(
            viewer_role,
            overwrite=viewer_overwrite,
            reason="Allow Archive Viewer to read every archive room",
        )
        viewer_overwrites_updated += 1

    print()
    print("=" * 60)
    print("BIG BRAIN ARCHIVE STRUCTURE READY")
    print(f"New categories created: {created_categories}")
    print(f"New channels created:   {created_channels}")
    print(f"Viewer role: {viewer_role_name}")
    print(f"Viewer room permissions updated: {viewer_overwrites_updated}")
    print("=" * 60)

    await client.close()


client.run(TOKEN)
