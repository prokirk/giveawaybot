"""Inline query handler + ChosenInlineResult handler for verified share tracking."""
from __future__ import annotations

from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    SwitchInlineQueryChosenChat,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import database as db
from formatter import build_giveaway_post

SHARES_REQUIRED = 3


async def inline_query_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Fires when user activates the bot's inline mode.
    Query format: "gw_<id>"
    Returns the giveaway post as a shareable inline result.
    """
    query_text = update.inline_query.query.strip()

    if not query_text.startswith("gw_"):
        await update.inline_query.answer([], cache_time=1)
        return

    try:
        gw_id = int(query_text[3:])
    except ValueError:
        await update.inline_query.answer([], cache_time=1)
        return

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await update.inline_query.answer([], cache_time=1)
        return

    bot_me = await ctx.bot.get_me()
    post_text, deep_link = build_giveaway_post(gw, gw["entry_count"], bot_me.username)

    if gw.get("image_id"):
        from telegram import InlineQueryResultCachedPhoto
        results = [
            InlineQueryResultCachedPhoto(
                id=f"gw_{gw_id}",
                photo_file_id=gw["image_id"],
                title=f"Share Giveaway #{gw_id} — {gw['amount']}",
                description="Tap to send this giveaway to a friend or group!",
                caption=post_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Participate!", url=deep_link)
                ]]),
            )
        ]
    else:
        results = [
            InlineQueryResultArticle(
                id=f"gw_{gw_id}",
                title=f"Share Giveaway #{gw_id} — {gw['amount']}",
                description="Tap to send this giveaway to a friend or group!",
                input_message_content=InputTextMessageContent(
                    message_text=post_text,
                    parse_mode=ParseMode.MARKDOWN,
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Participate!", url=deep_link)
                ]]),
                thumbnail_url="https://i.imgur.com/2nCt3Sbl.jpg",
            )
        ]

    await update.inline_query.answer(
        results,
        cache_time=30,
        is_personal=True,
    )


async def chosen_inline_result_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Fires when a user ACTUALLY selects and sends an inline result to a chat.
    This is how we verify the share happened — Telegram API confirmed.
    Requires inline feedback set to 100% in BotFather (/setinlinefeedback).
    """
    result = update.chosen_inline_result
    user = result.from_user
    result_id = result.result_id  # "gw_<id>"

    if not result_id.startswith("gw_"):
        return

    try:
        gw_id = int(result_id[3:])
    except ValueError:
        return

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        return

    # Check they've already entered (shouldn't share after entering)
    if await db.has_entered(gw_id, user.id):
        return

    # Increment verified share count
    share_count = await db.increment_inline_share(gw_id, user.id)
    remaining = SHARES_REQUIRED - share_count

    if share_count >= SHARES_REQUIRED:
        # ✅ Enough shares — send confirm button
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🎉 Confirm My Entry!",
                callback_data=f"confirm_entry_{gw_id}"
            )
        ]])
        try:
            await ctx.bot.send_message(
                chat_id=user.id,
                text=(
                    f"✅ *3/3 Shares Verified!*\n\n"
                    f"Telegram confirmed you shared the giveaway to 3 chats.\n\n"
                    f"Click below to lock in your entry 👇"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
        except Exception:
            pass
    else:
        # Progress update
        try:
            await ctx.bot.send_message(
                chat_id=user.id,
                text=(
                    f"📊 Share *{share_count}/{SHARES_REQUIRED}* verified!\n"
                    f"Share to *{remaining}* more chat(s) to unlock your entry."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
