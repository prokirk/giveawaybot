"""User-facing handlers: /start, share flow, captcha, participate confirm."""
from __future__ import annotations
import io
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

import database as db
from captcha import generate_captcha, generate_token
from formatter import build_giveaway_post, time_remaining

SHARES_REQUIRED = 3

# Conversation states
CAPTCHA_WAIT = 50
CONFIRM_WAIT = 51


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args

    # ── Plain /start: show active giveaways ───────────────────────────────────
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

    # ── Referral click from another user's share ───────────────────────────────
    if param.startswith("r") and len(param) == 16:
        await _handle_ref_click(update, ctx, param)
        return ConversationHandler.END

    # ── Giveaway entry deep-link ───────────────────────────────────────────────
    if param.startswith("gw_"):
        try:
            gw_id = int(param[3:])
        except ValueError:
            await update.message.reply_text("❓ Invalid link.")
            return ConversationHandler.END
        return await _handle_gw_entry(update, ctx, gw_id)

    await update.message.reply_text("❓ Unknown link.")
    return ConversationHandler.END


async def _handle_ref_click(update: Update, ctx: ContextTypes.DEFAULT_TYPE, token: str):
    """A user clicked someone else's share link."""
    user = update.effective_user
    ref = await db.get_ref_info(token)
    if not ref:
        await update.message.reply_text("❌ Invalid or expired share link.")
        return

    gw_id = ref["giveaway_id"]
    referrer_id = ref["referrer_id"]

    # Don't allow self-clicks
    if user.id == referrer_id:
        await update.message.reply_text(
            "ℹ️ You cannot use your own share link!\n"
            "Share it with friends and come back via the main participate button."
        )
        return

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await update.message.reply_text("⏰ This giveaway has already ended.")
        return

    # Register click
    is_new = await db.add_share_click(token, user.id)
    count = await db.count_share_clicks(token)

    if is_new and count >= SHARES_REQUIRED:
        # Notify referrer they've unlocked participation
        try:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎉 Participate Now!", callback_data=f"participate_{gw_id}")
            ]])
            await ctx.bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"✅ *3/3 shares done!*\n\n"
                    f"You've unlocked entry into Giveaway *#{gw_id}*!\n"
                    f"Click below to participate 👇"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
        except Exception:
            pass
    elif is_new:
        # Update referrer on progress
        try:
            await ctx.bot.send_message(
                chat_id=referrer_id,
                text=f"👥 *{count}/{SHARES_REQUIRED}* friends joined via your link for GW #{gw_id}!",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    # Also show this user the giveaway
    bot_me = await ctx.bot.get_me()
    text, deep_link = build_giveaway_post(gw, gw["entry_count"], bot_me.username)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎉 Participate!", url=deep_link)
    ]])
    await update.message.reply_text(
        f"👋 You were invited to a giveaway!\n\n{text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def _handle_gw_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE, gw_id: int):
    """User clicked the main participate link."""
    user = update.effective_user
    bot_me = await ctx.bot.get_me()

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

    # ── Check channel membership (strict GW) ──────────────────────────────────
    if gw["type"] == "strict" and gw.get("channel"):
        channel = gw["channel"]
        try:
            member = await ctx.bot.get_chat_member(chat_id=channel, user_id=user.id)
            if member.status in ("left", "kicked", "banned"):
                raise Exception("not member")
        except Exception:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel.lstrip('@')}")
            ]])
            await update.message.reply_text(
                f"❌ You must join *{channel}* first!",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
            )
            return ConversationHandler.END

    # ── Check share requirement ────────────────────────────────────────────────
    ref_token = await db.get_or_create_ref_token(user.id, gw_id)
    click_count = await db.count_share_clicks(ref_token)

    if click_count < SHARES_REQUIRED:
        remaining_shares = SHARES_REQUIRED - click_count
        share_link = f"https://t.me/{bot_me.username}?start={ref_token}"

        # Send the giveaway post so user can understand what to share
        text, _ = build_giveaway_post(gw, gw["entry_count"], bot_me.username)
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
        )
        await update.message.reply_text(
            f"🔗 *Share Required!*\n\n"
            f"Share your personal link with *{remaining_shares}* more friend(s) to unlock entry.\n\n"
            f"Your link:\n`{share_link}`\n\n"
            f"_{SHARES_REQUIRED - click_count}/{SHARES_REQUIRED} shares remaining_\n\n"
            f"💡 Forward this link to friends — when they click it, it counts as a share!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    # ── Shares done — send captcha ─────────────────────────────────────────────
    return await _send_captcha(update, ctx, gw_id)


async def participate_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Called when user clicks 'Participate Now!' after 3 shares."""
    q = update.callback_query
    await q.answer()
    gw_id = int(q.data.split("_")[1])
    user = q.from_user

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await q.edit_message_text("⏰ This giveaway has already ended.")
        return ConversationHandler.END

    if await db.has_entered(gw_id, user.id):
        await q.edit_message_text("✅ You are already entered! Good luck 🍀")
        return ConversationHandler.END

    return await _send_captcha(update, ctx, gw_id, via_callback=True)


async def _send_captcha(update, ctx, gw_id: int, via_callback=False):
    """Generate and send a captcha image to the user."""
    user = update.effective_user if not via_callback else update.callback_query.from_user
    img_bytes, answer = generate_captcha()
    token = generate_token()
    await db.save_captcha(token, user.id, gw_id, answer)

    ctx.user_data["captcha_token"] = token
    ctx.user_data["captcha_gw_id"] = gw_id

    target = update.message if not via_callback else update.callback_query.message

    await target.reply_photo(
        photo=io.BytesIO(img_bytes),
        caption=(
            "🔐 *Security Check*\n\n"
            "Solve the math problem and type your answer.\n"
            "You have *3 attempts*.\n\n"
            "_(Prevents bots from entering)_"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    return CAPTCHA_WAIT


async def captcha_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle captcha text answer."""
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
                "🚫 Too many wrong attempts. Use the participate link again for a new captcha."
            )
            return ConversationHandler.END
        await update.message.reply_text(
            f"❌ Wrong! *{remaining}* attempt(s) left.", parse_mode=ParseMode.MARKDOWN
        )
        return CAPTCHA_WAIT

    # ── Captcha passed — show confirm button ───────────────────────────────────
    await db.delete_captcha(token)
    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await update.message.reply_text("⏰ Giveaway ended while solving captcha.")
        return ConversationHandler.END

    ctx.user_data["pending_gw_id"] = gw_id
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm Entry", callback_data=f"confirm_entry_{gw_id}")
    ]])
    await update.message.reply_text(
        f"✅ *Captcha solved!*\n\n"
        f"Click the button below to *confirm your entry* into Giveaway #{gw_id}.\n"
        f"💰 Prize: `{gw['amount']}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )
    return CONFIRM_WAIT


async def confirm_entry_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Final confirm button click — records the entry."""
    q = update.callback_query
    await q.answer()
    user = q.from_user
    gw_id = int(q.data.split("_")[-1])

    gw = await db.get_giveaway(gw_id)
    if not gw or gw["status"] != "running":
        await q.edit_message_text("⏰ Giveaway ended.")
        return ConversationHandler.END

    username = user.username or ""
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")

    added = await db.add_entry(gw_id, user.id, username, full_name)
    if not added:
        await q.edit_message_text("✅ Already entered! Good luck 🍀")
        return ConversationHandler.END

    count = await db.get_entry_count(gw_id)
    await db.update_entry_count(gw_id, count)

    await q.edit_message_text(
        f"🎉 *Entry #{count} Confirmed!*\n\n"
        f"You're in Giveaway *#{gw_id}*!\n"
        f"💰 Prize: `{gw['amount']}`\n\n"
        f"Good luck! 🍀",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END
