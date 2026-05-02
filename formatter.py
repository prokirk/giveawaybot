from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

USA_TZ = ZoneInfo("America/New_York")


def fmt_dt(dt_val) -> str:
    """Format a datetime (or ISO string) to IST with proper spacing."""
    try:
        if isinstance(dt_val, str):
            dt = datetime.fromisoformat(dt_val)
        else:
            dt = dt_val  # already a datetime from psycopg2

        # Ensure UTC, then convert to USA time
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_usa = dt.astimezone(USA_TZ)
        return dt_usa.strftime("%b %d, %Y  %I:%M %p EDT/EST")
    except Exception:
        return str(dt_val)


def time_remaining(end_val) -> str:
    """Return a human-readable time remaining string."""
    try:
        if isinstance(end_val, str):
            end = datetime.fromisoformat(end_val)
        else:
            end = end_val

        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = end - now
        if diff.total_seconds() <= 0:
            return "Ended"
        total_secs = int(diff.total_seconds())
        days  = total_secs // 86400
        hours = (total_secs % 86400) // 3600
        mins  = (total_secs % 3600) // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{mins}m")
        return " ".join(parts)
    except Exception:
        return "Unknown"


def build_giveaway_post(gw: dict, entry_count: int, bot_username: str) -> tuple[str, str]:
    """Build the giveaway post text and deep-link URL."""
    gw_id       = gw["id"]
    gw_type     = gw["type"]
    amount      = gw["amount"]
    description = gw.get("description") or ""
    end_val     = gw["end_time"]
    channel     = gw.get("channel") or ""

    remaining    = time_remaining(end_val)
    end_display  = fmt_dt(end_val)
    deep_link    = f"https://t.me/{bot_username}?start=gw_{gw_id}"

    header = "GIVEAWAY\n"

    body = f"Prize: `{amount}`\n"
    if description:
        body += f"{description}\n"

    body += "\nRequirements:\n"
    if gw_type == "strict" and channel:
        body += (
            f"- Join {channel}\n"
            f"- Be an active member (top texters win)\n"
            f"- No bots / alts\n"
        )
        if gw.get("discussion_link"):
            body += f"- Discussion: {gw['discussion_link']}\n"
    else:
        body += (
            f"- Click Participate below\n"
            f"- Complete the verification\n"
            f"- No bots / alts\n"
        )

    body += (
        f"\nGiveaway Details:\n"
        f"- Winners: 1\n"
        f"- Ends: {end_display}\n"
        f"- Time Left: {remaining}\n"
        f"- Current Entries: *{entry_count}*\n"
    )

    text = header + body
    return text, deep_link


def build_winner_announcement(gw: dict, winner_username: str, winner_id: int, entry_count: int) -> str:
    amount  = gw["amount"]
    mention = f"@{winner_username}" if winner_username else f"[User](tg://user?id={winner_id})"

    return (
        f"Giveaway Ended\n\n"
        f"Winner: {mention}\n"
        f"Prize: `{amount}`\n"
        f"Total Entries: {entry_count}\n\n"
        f"Thank you all for participating."
    )
