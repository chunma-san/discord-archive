"""Format source-guild references for readable archive messages.

User mentions open profiles. Channel references use Discord channel links so
they can navigate from the archive guild to the source guild.
"""

import re


_ROLE_MENTION = re.compile(r"<@&(\d+)>")
_CHANNEL_MENTION = re.compile(r"<#(\d+)>")
_CHANNEL_LABEL_WITH_ID = re.compile(
    r"#(?P<name>[^\n()]+?)\s+\(ID:\s*`?(?P<id>\d+)`?\)"
)
_CHANNEL_FIELD_WITH_ID = re.compile(
    r"(?m)(?P<prefix>\*\*(?:Channel|From|To):\*\*\s*)"
    r"(?P<name>[^\n]+?)\s+\(\s*`?(?P<id>\d+)`?\s*\)"
)
_ID_FIELD = re.compile(
    r"\*\*(User ID|Owner ID|Creator ID|Role ID|Channel ID|Category ID|"
    r"Parent ID|Before category ID|After category ID):\*\*\s*`?(\d+)`?"
)
_LEGACY_PROFILE_LINE = re.compile(
    r"(?m)^\*\*(?P<label>User|Owner|Creator|Author|Actor|Moderator|"
    r"Inviter|Created by|Changed by|Deleted by):\*\*.*?"
    r"(?:\(ID:\s*`?(?P<explicit>\d+)`?\)|"
    r"\s+\(`?(?P<plain>\d+)`?\))\s*$"
)


def _safe_name(value):
    text = str(value or "").strip()
    # Prevent user-controlled display names from becoming fake mentions or
    # breaking inline-code formatting in archive embeds.
    text = text.replace("<@", "<\u200b@")
    text = text.replace("`", "ˋ")
    return text


def user_label(user=None, user_id=None, fallback_name=None):
    if user is not None:
        display = (
            getattr(user, "display_name", None)
            or getattr(user, "global_name", None)
            or getattr(user, "name", None)
        )
        username = getattr(user, "name", None)
        if username and display and username != display:
            display = f"{display} (@{username})"
        user_id = user_id or getattr(user, "id", None)
    else:
        display = fallback_name

    display = _safe_name(display) or "Unknown user"
    return f"{display} (ID: `{user_id}`)" if user_id else display


def role_label(role=None, role_id=None, fallback_name=None):
    if role is not None:
        name = getattr(role, "name", None)
    else:
        name = fallback_name

    name = _safe_name(name) or "Unknown role"
    return f"@{name}"


def channel_label(channel=None, channel_id=None, fallback_name=None):
    if channel is not None:
        name = getattr(channel, "name", None)
        channel_id = channel_id or getattr(channel, "id", None)
    else:
        name = fallback_name

    name = _safe_name(name) or "Unknown channel"
    return f"#{name} (ID: `{channel_id}`)" if channel_id else f"#{name}"


def channel_link(
    channel=None,
    channel_id=None,
    fallback_name=None,
    guild_id=None,
):
    """Return a readable source-channel link without exposing its numeric ID."""
    if channel is not None:
        channel_id = channel_id or getattr(channel, "id", None)
        channel_guild = getattr(channel, "guild", None)
        guild_id = guild_id or getattr(channel_guild, "id", None)
        name = getattr(channel, "name", None)
    else:
        name = fallback_name

    name = _safe_name(name) or "Unknown channel"
    # Discord channel names normally need no escaping, but fallbacks can be
    # arbitrary text and should not break the Markdown link label.
    label = name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    if channel_id and guild_id:
        return (
            f"[#{label}](https://discord.com/channels/"
            f"{guild_id}/{channel_id})"
        )
    return f"#{name}"


def category_label(category):
    return _safe_name(getattr(category, "name", None)) if category else "None"


def _source_user(guild, user_id):
    if guild is None:
        return None
    return guild.get_member(user_id)


def _source_channel(guild, channel_id):
    if guild is None:
        return None
    getter = getattr(guild, "get_channel_or_thread", guild.get_channel)
    return getter(channel_id)


def normalize_source_references(description, guild):
    """Keep user profiles clickable and label guild-scoped references."""

    def role_ref(match):
        role_id = int(match.group(1))
        role = guild.get_role(role_id) if guild else None
        return role_label(role, role_id=role_id).split(" (ID:", 1)[0]

    def channel_ref(match):
        channel_id = int(match.group(1))
        channel = _source_channel(guild, channel_id)
        return channel_link(
            channel,
            channel_id=channel_id,
            fallback_name=(
                getattr(channel, "name", None)
                or "Unknown channel"
            ),
            guild_id=getattr(guild, "id", None),
        )

    def linked_channel_label(match):
        channel_id = int(match.group("id"))
        channel = _source_channel(guild, channel_id)
        return channel_link(
            channel,
            channel_id=channel_id,
            fallback_name=match.group("name"),
            guild_id=getattr(guild, "id", None),
        )

    def linked_channel_field(match):
        channel_id = int(match.group("id"))
        channel = _source_channel(guild, channel_id)
        raw_name = match.group("name").strip()
        mention = re.fullmatch(r"<#\d+>", raw_name)
        return (
            match.group("prefix")
            + channel_link(
                channel,
                channel_id=channel_id,
                fallback_name=(
                    getattr(channel, "name", None)
                    or ("Unknown channel" if mention else raw_name.strip("`"))
                ),
                guild_id=getattr(guild, "id", None),
            )
        )

    def id_field(match):
        field, raw_id = match.groups()
        entity_id = int(raw_id)

        if field in ("User ID", "Owner ID", "Creator ID"):
            return ""
        elif field == "Role ID":
            role = guild.get_role(entity_id) if guild else None
            if re.search(r"\*\*Role:\*\*", description):
                return ""
            return f"**Role:** {role_label(role, fallback_name='Unknown role').split(' (ID:', 1)[0]}"
        else:
            channel = _source_channel(guild, entity_id)
            if field == "Channel ID":
                if re.search(r"\*\*Channel:\*\*", description):
                    return ""
                return (
                    f"**Channel:** "
                    f"{channel_link(channel, channel_id=entity_id, guild_id=getattr(guild, 'id', None))}"
                )
            label = {
                "Category ID": "Category",
                "Parent ID": "Parent channel",
                "Before category ID": "Before category",
                "After category ID": "After category",
            }[field]
            if field == "Parent ID":
                value = channel_link(
                    channel,
                    channel_id=entity_id,
                    guild_id=getattr(guild, "id", None),
                )
                return f"**{label}:** {value}"
            # Discord has no useful channel-navigation target for category
            # containers. Keep those names readable and omit the raw IDs.
            category_name = _safe_name(getattr(channel, "name", None))
            return f"**{label}:** {category_name or 'Unknown'}"

    # Keep user mentions clickable in the archive guild. Discord resolves
    # user profiles across guilds, while role/channel IDs are guild-scoped.
    # Add a mention when a log only contains a user ID, or replace a plain
    # username field (member-leave and similar events) with the clickable tag.
    for match in list(_ID_FIELD.finditer(description)):
        field, raw_id = match.groups()
        if field not in ("User ID", "Owner ID", "Creator ID"):
            continue
        user_id = int(raw_id)
        label = {
            "User ID": "User",
            "Owner ID": "Owner",
            "Creator ID": "Creator",
        }[field]
        line = re.compile(rf"(?m)^\*\*{label}:\*\*.*$")
        existing_line = line.search(description)
        if existing_line and re.search(
            rf"<@!?{user_id}>",
            existing_line.group(0),
        ):
            continue
        if existing_line:
            description = line.sub(
                f"**{label}:** <@{user_id}>",
                description,
                count=1,
            )
        else:
            description = description.replace(
                match.group(0),
                f"**{label}:** <@{user_id}>\n{match.group(0)}",
                1,
            )

    def legacy_profile(match):
        user_id = match.group("explicit") or match.group("plain")
        return f"**{match.group('label')}:** <@{user_id}>"

    description = _LEGACY_PROFILE_LINE.sub(legacy_profile, description)
    description = _ROLE_MENTION.sub(role_ref, description)
    # Some voice logs use a plain room name followed by its ID rather than a
    # Discord channel mention. Resolve both forms before cleaning IDs away.
    description = re.sub(
        r"(<#(?P<id>\d+)>)\s*\(\s*`?(?P=id)`?\s*\)",
        r"\1",
        description,
    )
    description = _CHANNEL_FIELD_WITH_ID.sub(
        linked_channel_field,
        description,
    )
    description = _CHANNEL_MENTION.sub(channel_ref, description)
    description = _CHANNEL_LABEL_WITH_ID.sub(linked_channel_label, description)
    description = _ID_FIELD.sub(id_field, description)
    # Avoid showing raw IDs beside a clickable profile mention.
    description = re.sub(
        r"(?P<mention><@!?(?P<id>\d+)>)(?P<bold>\*\*)?"
        r"\s*\(\s*`?(?P=id)`?\s*\)",
        r"\g<mention>\g<bold>",
        description,
    )
    description = re.sub(
        r"(?m)^(\*\*(?:User|Owner|Creator):\*\* <@!?\d+>\*?\*?)\n\n",
        r"\1\n",
        description,
    )
    return re.sub(r"\n{3,}", "\n\n", description).strip()
