"""Scheduled jobs: update post counts, auto-end giveaways, notify admins of winner."""
from __future__ import annotations
import os
import random
from datetime import datetime

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import database as db
from formatter import build_giveaway_post, build_winner_announcement

OWNER_ID = int(os.getenv("OWNER_ID", "0"))


async def update_all_posts(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 60s — refresh entry counts and auto-end expired giveaways."""
    bot = context.bot
    bot_me = await bot.get_me()
    bot_username = bot_me.username
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    gws = await db.get_running_giveaways()
    for gw in gws:
        gw_id = gw["id"]
        try:
            end = gw["end_time"]
            if hasattr(end, "replace"):
                end = end.replace(tzinfo=None)
        except Exception:
            continue

        now = datetime.utcnow()

        if now >= end:
            await _end_giveaway(bot, gw, bot_username)
            continue

        # Update count on post
        count = await db.get_entry_count(gw_id)
        await db.update_entry_count(gw_id, count)

        msg_id = gw.get("message_id")
        chat_id = gw.get("chat_id")
        if not msg_id or not chat_id:
            continue

        fresh = await db.get_giveaway(gw_id)
        text, deep_link = build_giveaway_post(fresh, count, bot_username)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎉 Participate!", url=deep_link)],
            [InlineKeyboardButton("🔗 Share", switch_inline_query=f"gw_{gw_id}")],
        ])
        try:
            if fresh.get("image_id"):
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=msg_id,
                    caption=text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
                )
        except Exception:
            pass


async def _end_giveaway(bot, gw: dict, bot_username: str):
    gw_id = gw["id"]
    gw_type = gw["type"]
    msg_id = gw.get("message_id")
    chat_id = gw.get("chat_id")
    created_by = gw.get("created_by")

    entries = await db.get_all_entries(gw_id)
    if not entries:
        await db.end_giveaway(gw_id, 0, "No entries")
        if msg_id and chat_id:
            try:
                if gw.get("image_id"):
                    await bot.edit_message_caption(
                        chat_id=chat_id, message_id=msg_id,
                        caption="⏰ *Giveaway ended — No entries received.*",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=msg_id,
                        text="⏰ *Giveaway ended — No entries received.*",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception:
                pass
        return

    # Pick winner
    if gw_type == "strict":
        pool = await db.get_top_texters(gw_id, top_percent=0.10)
        if not pool:
            pool = entries
        winner = random.choice(pool)
        winner_id = winner["user_id"]
        winner_username = winner.get("username", "")
    else:
        w = random.choice(entries)
        winner_id = w["user_id"]
        winner_username = w.get("username", "")

    await db.end_giveaway(gw_id, winner_id, winner_username)

    count = len(entries)
    fresh = await db.get_giveaway(gw_id)
    announcement = build_winner_announcement(fresh, winner_username, winner_id, count)

    # Edit post
    if msg_id and chat_id:
        try:
            if fresh.get("image_id"):
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=msg_id,
                    caption=announcement, parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=announcement, parse_mode=ParseMode.MARKDOWN,
                )
        except Exception:
            pass

    # DM winner
    try:
        await bot.send_message(
            chat_id=winner_id,
            text=(
                f"🏆 *Congratulations!* You won Giveaway #{gw_id}!\n"
                f"💰 Prize: `{gw['amount']}`\n\n"
                f"An admin will contact you shortly."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    # ── Notify admins + owner about winner ────────────────────────────────────
    winner_mention = f"@{winner_username}" if winner_username else f"ID: {winner_id}"
    admin_notice = (
        f"🏆 *GW #{gw_id} Winner Selected*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Winner:* {winner_mention} (`{winner_id}`)\n"
        f"💰 *Prize:* `{gw['amount']}`\n"
        f"👥 *Total Entries:* {count}\n"
        f"🎯 *Type:* {gw_type.upper()}"
    )

    notify_ids = {OWNER_ID}
    if created_by:
        notify_ids.add(created_by)
    admins = await db.get_admins()
    for a in admins:
        notify_ids.add(a["user_id"])

    for uid in notify_ids:
        if uid and uid != winner_id:
            try:
                await bot.send_message(
                    chat_id=uid, text=admin_notice, parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass


async def track_discussion_messages(update, context: ContextTypes.DEFAULT_TYPE):
    """Count messages in discussion groups for strict GWs."""
    if not update.message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or user.is_bot:
        return

    gws = await db.get_running_giveaways()
    for gw in gws:
        if gw["type"] == "strict" and gw.get("discussion_link"):
            disc = gw["discussion_link"].lower().strip().rstrip("/")
            chat_link = f"https://t.me/{chat.username}".lower() if chat.username else ""
            if chat_link and disc.endswith(chat.username.lower() if chat.username else ""):
                await db.increment_msg_count(gw["id"], user.id, user.username or "")
                break
