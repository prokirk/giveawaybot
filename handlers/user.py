"""User-facing handlers: captcha → inline share (verified) → confirm entry."""
from __future__ import annotations
import io
import os

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    SwitchInlineQueryChosenChat,
)
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

import database as db
from captcha import generate_captcha, generate_token
from formatter import build_giveaway_post, time_remaining

# Conversation states
CAPTCHA_WAIT = 50


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args

    # Plain /start — list active giveaways
    if not args:
        gws = await db.get_running_giveaways()
        if not gws:
            await update.message.reply_text(
                f"👋 Hello *{user.first_name}*!\n\nNo active giveaways right now. Stay tuned!",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

        lines = [
            f"• *GW #{g['id']}* — 💰 {g['amount']} | "
            f"👥 {g['entry_count']} entries | ⏳ {time_remaining(str(g['end_time']))}"
            for g in gws
        ]
        await update.message.reply_text(
            f"👋 Hello *{user.first_name}*!\n\n🎉 *Active Giveaways:*\n" + "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    param = args[0]
    if not param.startswith("gw_"):
        await update.message.reply_text("❓ Unknown link.")
        return ConversationHandler.END

    try:
        gw_id = int(param[3:])
    except ValueError:
        await update.message.reply_text("❓ Invalid giveaway link.")
        return ConversationHandler.END

    # ── Validate giveaway ──────────────────────────────────────────────────────
    gw = await db.get_giveaway(gw_id)
    if not gw:
        await update.message.reply_text("❌ Giveaway not found.")
        return ConversationHandler.END
    if gw["status"] != "running":
        await update.message.reply_text("⏰ This giveaway has already ended.")
        return ConversationHandler.END
    if await db.has_entered(gw_id, user.id):
        await update.message.reply_text(
            "✅ You are *already entered!* Good luck 🍀", parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    # ── Strict GW: channel membership check ───────────────────────────────────
    if gw["type"] == "strict" and gw.get("channel"):
        channel = gw["channel"]
        try:
            member = await ctx.bot.get_chat_member(chat_id=channel, user_id=user.id)
            if member.status in ("left", "kicked", "banned"):
                raise Exception("not member")
        except Exception:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"Join {channel}",
                    url=f"https://t.me/{channel.lstrip('@')}"
                )
            ]])
            await update.message.reply_text(
                f"❌ You must join *{channel}* first to participate!",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
            )
            return ConversationHandler.END

    # ── Step 1: Send captcha ───────────────────────────────────────────────────
    ctx.user_data["captcha_gw_id"] = gw_id
    return await _send_captcha(update.message, ctx, gw_id, user.id)


# ── Captcha helpers ────────────────────────────────────────────────────────────

async def _send_captcha(target, ctx, gw_id: int, user_id: int):
    img_bytes, answer = generate_captcha()
    token = generate_token()
    await db.save_captcha(token, user_id, gw_id, answer)
    ctx.user_data["captcha_token"] = token
    ctx.user_data["captcha_gw_id"] = gw_id

    await target.reply_photo(
        photo=io.BytesIO(img_bytes),
        caption=(
            "🔐 *Security Check — Step 1 of 3*\n\n"
            "Solve the math problem in the image and *type your answer*.\n"
            "You have *3 attempts*.\n\n"
            "_(This prevents bots from entering)_"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    return CAPTCHA_WAIT


async def captcha_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    answer_text = update.message.text.strip()
    token = ctx.user_data.get("captcha_token")
    gw_id = ctx.user_data.get("captcha_gw_id")

    if not token or not gw_id:
        await update.message.reply_text("❌ Session expired. Use the participate link again.")
        return ConversationHandler.END

    captcha = await db.get_captcha(token)
    if not captcha:
        await update.message.reply_text("❌ Captcha expired. Use the participate link again.")
        return ConversationHandler.END

    attempts = await db.increment_captcha_attempts(token)

    if answer_text != captcha["answer"]:
        remaining = 3 - attempts
        if remaining <= 0:
            await db.delete_captcha(token)
            await update.message.reply_text(
                "🚫 Too many wrong attempts. Use the participate link again."
            )
            return ConversationHandler.END
        await update.message.reply_text(
            f"❌ Wrong answer! *{remaining}* attempt(s) left.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return CAPTCHA_WAIT

    # ── Captcha passed ─────────────────────────────────────────────────────────
    await db.delete_captcha(token)

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await update.message.reply_text("⏰ Giveaway ended while solving captcha.")
        return ConversationHandler.END

    # ── Step 2: Send GW post with VERIFIED share button ───────────────────────
    bot_me = await ctx.bot.get_me()
    post_text, deep_link = build_giveaway_post(gw, gw["entry_count"], bot_me.username)

    await update.message.reply_text(
        f"✅ *Captcha solved!*\n\n"
        f"*Step 2 of 3 — Share this giveaway*\n\n"
        f"Press the *Share* button below and send the giveaway to *3 different chats or friends*.\n\n"
        f"⚠️ Telegram verifies each share — the bot will automatically count them.\n"
        f"After *3 confirmed shares*, your entry confirmation will be sent here.",
        parse_mode=ParseMode.MARKDOWN,
    )

    # send the GW post with a share button (switch_inline_query sends via inline)
    share_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📢 Share Giveaway (1/3)",
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query=f"gw_{gw_id}",
                allow_user_chats=True,
                allow_bot_chats=False,
                allow_group_chats=True,
                allow_channel_chats=False,
            ),
        )
    ]])
    await update.message.reply_text(
        post_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=share_kb,
    )
    # Share tracking now handled async via ChosenInlineResult in handlers/inline.py
    return ConversationHandler.END


# ── Confirm entry callback (standalone — triggered after 3 verified shares) ───────────

async def confirm_entry_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    gw_id = int(q.data.split("_")[-1])

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await q.edit_message_text("⏰ Giveaway ended.")
        return ConversationHandler.END

    if await db.has_entered(gw_id, user.id):
        await q.edit_message_text("✅ You're already entered! Good luck 🍀")
        return ConversationHandler.END

    username = user.username or ""
    full_name = (user.first_name or "") + (f" {user.last_name}" if user.last_name else "")

    added = await db.add_entry(gw_id, user.id, username, full_name)
    if not added:
        await q.edit_message_text("✅ Already entered! Good luck 🍀")
        return ConversationHandler.END

    count = await db.get_entry_count(gw_id)
    await db.update_entry_count(gw_id, count)

    await q.edit_message_text(
        f"🏅 *Entry #{count} Confirmed!*\n\n"
        f"You're officially in Giveaway *#{gw_id}*!\n"
        f"💰 Prize: `{gw['amount']}`\n\n"
        f"Good luck! 🍀\n"
        f"Winner announced when the giveaway ends.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END
