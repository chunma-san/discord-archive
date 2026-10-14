import os
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
SOURCE_GUILD_ID = int(os.getenv("SOURCE_GUILD_ID"))
ARCHIVE_GUILD_ID = int(os.getenv("ARCHIVE_GUILD_ID"))

intents = discord.Intents.all()
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print("=" * 50)
    print(f"Logged in as: {client.user}")
    print(f"Bot ID: {client.user.id}")
    print("=" * 50)

    source = client.get_guild(SOURCE_GUILD_ID)
    archive = client.get_guild(ARCHIVE_GUILD_ID)

    if source:
        print(f"Source Guild  : OK -> {source.name}")
        print(f"Members: {source.member_count}")
        print(f"Channels: {len(source.channels)}")
        print(f"Roles: {len(source.roles)}")
    else:
        print("Source Guild  : NOT FOUND")

    print("-" * 50)

    if archive:
        print(f"Archive Guild : OK -> {archive.name}")
        print(f"Members: {archive.member_count}")
        print(f"Channels: {len(archive.channels)}")
        print(f"Roles: {len(archive.roles)}")
    else:
        print("Archive Guild : NOT FOUND")

    print("=" * 50)
    print("Connection test complete.")
    print("Press CTRL+C to stop.")


client.run(TOKEN)
