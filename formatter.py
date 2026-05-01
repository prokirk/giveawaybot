from datetime import datetime, timezone
from typing import Optional


def fmt_dt(iso: str) -> str:
    """Format ISO datetime to human-readable."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%b %d, %Y at %I:%M %p UTC")
    except Exception:
        return iso


def time_remaining(end_iso: str) -> str:
    """Return a human-readable time remaining string."""
    try:
        end = datetime.fromisoformat(end_iso)
        now = datetime.utcnow()
        diff = end - now
        if diff.total_seconds() <= 0:
            return "⏰ Ended"
        total_secs = int(diff.total_seconds())
        days = total_secs // 86400
        hours = (total_secs % 86400) // 3600
        minutes = (total_secs % 3600) // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)
    except Exception:
        return "Unknown"


def build_giveaway_post(gw: dict, entry_count: int, bot_username: str) -> tuple[str, str]:
    """
    Build the giveaway post text and the deep-link URL.
    Returns (post_text, deep_link_url).
    """
    gw_id = gw["id"]
    gw_type = gw["type"]
    amount = gw["amount"]
    description = gw.get("description") or ""
    end_iso = gw["end_time"]
    channel = gw.get("channel") or ""

    remaining = time_remaining(end_iso)
    end_display = fmt_dt(end_iso)

    deep_link = f"https://t.me/{bot_username}?start=gw_{gw_id}"

    # ── Header ─────────────────────────────────────────────────────────────────
    if gw_type == "active":
        header = (
            f"🎉 *GIVEAWAY — Active Channel Edition* 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    else:
        header = (
            f"🎉 *GIVEAWAY* 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    # ── Body ───────────────────────────────────────────────────────────────────
    body = f"💰 *Prize:* `{amount}`\n"

    if description:
        body += f"📝 *Info:* {description}\n"

    body += "\n*Requirements:*\n"

    if gw_type == "active" and channel:
        body += (
            f"• Join {channel}\n"
            f"• Be an active member (top 10% texters WIN!)\n"
            f"• No bots / alts will be allowed!\n"
        )
        if gw.get("discussion_link"):
            body += f"• Discussion: {gw['discussion_link']}\n"
    else:
        body += (
            f"• Click *Participate* button below\n"
            f"• Complete the verification\n"
            f"• No bots / alts will be allowed!\n"
        )

    # ── Stats ──────────────────────────────────────────────────────────────────
    body += (
        f"\n*Giveaway Details:*\n"
        f"• 🏆 Winners: 1\n"
        f"• 📅 Ends: {end_display}\n"
        f"• ⏳ Time Left: {remaining}\n"
        f"• 👥 Current Entries: *{entry_count}*\n"
    )

    # ── Footer ─────────────────────────────────────────────────────────────────
    footer = (
        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 *CLICK THE BUTTON BELOW* 👇"
    )

    text = header + body + footer
    return text, deep_link


def build_winner_announcement(gw: dict, winner_username: str, winner_id: int, entry_count: int) -> str:
    amount = gw["amount"]
    gw_type = gw["type"]

    mention = f"@{winner_username}" if winner_username else f"[User](tg://user?id={winner_id})"

    text = (
        f"🏆 *GIVEAWAY ENDED* 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 Congratulations to our winner!\n\n"
        f"👤 *Winner:* {mention}\n"
        f"💰 *Prize:* `{amount}`\n"
        f"👥 *Total Entries:* {entry_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Thank you all for participating! 🙏"
    )
    return text
