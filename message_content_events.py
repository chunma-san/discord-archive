import json


def setup_message_content_events(
    client,
    source_guild_id,
    send_log,
):
    def trim(value, limit=3500):
        if value is None:
            return ""

        value = str(value)

        if len(value) <= limit:
            return value

        return value[:limit - 3] + "..."


    def poll_snapshot(poll):
        if poll is None:
            return None

        answers = []

        for answer in poll.answers:
            answers.append(
                {
                    "id": getattr(answer, "id", None),
                    "text": getattr(answer, "text", None),
                    "vote_count": getattr(answer, "vote_count", None),
                    "self_voted": getattr(answer, "self_voted", None),
                    "emoji": (
                        str(answer.emoji)
                        if getattr(answer, "emoji", None)
                        else None
                    ),
                }
            )

        return {
            "question": str(poll.question),
            "multiple": poll.multiple,
            "total_votes": poll.total_votes,
            "expires_at": (
                poll.expires_at.isoformat()
                if poll.expires_at
                else None
            ),
            "finalized": poll.is_finalized(),
            "victor_answer_id": poll.victor_answer_id,
            "answers": answers,
        }


    async def log_message_created(message):
        content = message.content or "*No text content*"

        description = (
            f"**User:** {message.author.mention} "
            f"(`{message.author.id}`)\n"
            f"**Channel:** {message.channel.mention} "
            f"(`{message.channel.id}`)\n"
            f"**Message ID:** `{message.id}`\n"
            f"**Created:** `{message.created_at.isoformat()}`\n"
            f"**Bot:** `{message.author.bot}`\n"
            f"**Webhook:** `{message.webhook_id is not None}`\n"
            f"**Reply To:** "
            f"`{message.reference.message_id if message.reference else 'None'}`\n"
            f"**Attachments:** `{len(message.attachments)}`\n"
            f"**Embeds:** `{len(message.embeds)}`\n"
            f"**Poll:** `{message.poll is not None}`\n\n"
            f"**Content:**\n{trim(content)}"
        )

        await send_log(
            "message-created",
            "💬 Message Created",
            description,
        )


    async def log_embeds(message):
        if not message.embeds:
            return

        for index, embed in enumerate(message.embeds, start=1):
            try:
                data = embed.to_dict()

                description = (
                    f"**User:** {message.author.mention} "
                    f"(`{message.author.id}`)\n"
                    f"**Channel:** {message.channel.mention} "
                    f"(`{message.channel.id}`)\n"
                    f"**Message ID:** `{message.id}`\n"
                    f"**Embed:** `{index}/{len(message.embeds)}`\n"
                    f"**Type:** `{embed.type or 'Unknown'}`\n"
                    f"**Title:** `{trim(embed.title or 'None', 500)}`\n"
                    f"**URL:** `{trim(embed.url or 'None', 1000)}`\n\n"
                    f"**Embed JSON:**\n"
                    f"```json\n"
                    f"{trim(json.dumps(data, ensure_ascii=False, default=str), 2800)}"
                    f"\n```"
                )

                await send_log(
                    "embeds",
                    "🧩 Embed Detected",
                    description,
                )

            except Exception as e:
                await send_log(
                    "logger-errors",
                    "⚠️ Embed Logging Error",
                    (
                        f"**Message ID:** `{message.id}`\n"
                        f"**Error:** `{type(e).__name__}: {e}`"
                    ),
                )


    async def log_poll(message, title="📊 Poll Detected"):
        poll = message.poll

        if poll is None:
            return

        try:
            snapshot = poll_snapshot(poll)

            description = (
                f"**User:** {message.author.mention} "
                f"(`{message.author.id}`)\n"
                f"**Channel:** {message.channel.mention} "
                f"(`{message.channel.id}`)\n"
                f"**Message ID:** `{message.id}`\n"
                f"**Question:** `{trim(poll.question, 800)}`\n"
                f"**Multiple Choice:** `{poll.multiple}`\n"
                f"**Total Votes:** `{poll.total_votes}`\n"
                f"**Expires:** "
                f"`{poll.expires_at.isoformat() if poll.expires_at else 'None'}`\n"
                f"**Finalized:** `{poll.is_finalized()}`\n\n"
                f"**Poll JSON:**\n"
                f"```json\n"
                f"{trim(json.dumps(snapshot, ensure_ascii=False, default=str), 2600)}"
                f"\n```"
            )

            await send_log(
                "polls",
                title,
                description,
            )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Poll Logging Error",
                (
                    f"**Message ID:** `{message.id}`\n"
                    f"**Error:** `{type(e).__name__}: {e}`"
                ),
            )


    @client.listen("on_message")
    async def message_content_on_message(message):
        if message.guild is None:
            return

        if message.guild.id != source_guild_id:
            return

        try:
            await log_message_created(message)
            await log_embeds(message)
            await log_poll(message)

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Message Content Logger Error",
                (
                    f"**Message ID:** `{message.id}`\n"
                    f"**Error:** `{type(e).__name__}: {e}`"
                ),
            )


    @client.listen("on_message_edit")
    async def message_content_on_message_edit(before, after):
        if after.guild is None:
            return

        if after.guild.id != source_guild_id:
            return

        # Log only newly-added/changed embeds here.
        try:
            before_embeds = [
                embed.to_dict()
                for embed in before.embeds
            ]

            after_embeds = [
                embed.to_dict()
                for embed in after.embeds
            ]

            if before_embeds != after_embeds and after.embeds:
                await log_embeds(after)

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Embed Update Error",
                (
                    f"**Message ID:** `{after.id}`\n"
                    f"**Error:** `{type(e).__name__}: {e}`"
                ),
            )

        # Discord can expose an updated poll state through a
        # message update. Compare snapshots and log if changed.
        try:
            before_poll = poll_snapshot(before.poll)
            after_poll = poll_snapshot(after.poll)

            if (
                after.poll is not None
                and before_poll != after_poll
            ):
                await log_poll(
                    after,
                    "📊 Poll Updated",
                )

        except Exception as e:
            await send_log(
                "logger-errors",
                "⚠️ Poll Update Error",
                (
                    f"**Message ID:** `{after.id}`\n"
                    f"**Error:** `{type(e).__name__}: {e}`"
                ),
            )
