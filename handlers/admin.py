"""Admin panel conversation handlers."""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

import database as db
from formatter import build_giveaway_post

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ── Conversation states ────────────────────────────────────────────────────────
(
    ADMIN_MENU,
    ADD_ADMIN_ID, REMOVE_ADMIN_ID,
    GW_TYPE,
    GW_CHANNEL, GW_DISCUSSION, GW_AMOUNT, GW_DESCRIPTION, GW_DURATION,
    GW_CONFIRM,
    POST_CHANNEL,
) = range(11)


def admin_menu_keyboard(is_owner=False):
    kb = [
        [InlineKeyboardButton("⚡ Create Strict GW", callback_data="create_strict")],
        [InlineKeyboardButton("🎰 Create Normal GW", callback_data="create_normal")],
        [InlineKeyboardButton("📋 Running Giveaways", callback_data="list_gws")],
    ]
    if is_owner:
        kb += [
            [InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
             InlineKeyboardButton("➖ Remove Admin", callback_data="rm_admin")],
            [InlineKeyboardButton("👥 List Admins", callback_data="list_admins")],
        ]
    kb.append([InlineKeyboardButton("❌ Close", callback_data="close_panel")])
    return InlineKeyboardMarkup(kb)


async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_owner = uid == OWNER_ID
    if not is_owner and not await db.is_admin(uid):
        await update.message.reply_text("⛔ You don't have admin access.")
        return ConversationHandler.END

    ctx.user_data["is_owner"] = is_owner
    await update.message.reply_text(
        "🛠 *Admin Panel*\nSelect an option:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_menu_keyboard(is_owner),
    )
    return ADMIN_MENU


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id
    is_owner = uid == OWNER_ID

    if not is_owner and not await db.is_admin(uid):
        await q.edit_message_text("⛔ Access denied.")
        return ConversationHandler.END

    if data == "close_panel":
        await q.edit_message_text("✅ Panel closed.")
        return ConversationHandler.END

    elif data == "list_admins":
        admins = await db.get_admins()
        if not admins:
            text = "👥 *Admins:* None added yet."
        else:
            lines = [f"• `{a['user_id']}` — @{a['username'] or 'unknown'}" for a in admins]
            text = "👥 *Admins:*\n" + "\n".join(lines)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=admin_menu_keyboard(is_owner))
        return ADMIN_MENU

    elif data == "add_admin":
        await q.edit_message_text("Enter the Telegram user ID to add as admin:")
        return ADD_ADMIN_ID

    elif data == "rm_admin":
        await q.edit_message_text("Enter the Telegram user ID to remove from admins:")
        return REMOVE_ADMIN_ID

    elif data == "list_gws":
        gws = await db.get_running_giveaways()
        if not gws:
            text = "📋 No running giveaways."
        else:
            lines = []
            for g in gws:
                lines.append(
                    f"• *GW #{g['id']}* [{g['type']}] — 💰{g['amount']} — "
                    f"👥{g['entry_count']} entries"
                )
            text = "📋 *Running Giveaways:*\n" + "\n".join(lines)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=admin_menu_keyboard(is_owner))
        return ADMIN_MENU

    elif data == "create_strict":
        ctx.user_data["gw_type"] = "strict"
        await q.edit_message_text(
            "⚡ *Strict GW Setup*\n\nStep 1/5 — Send the channel username (e.g. `@MyChannel`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return GW_CHANNEL

    elif data == "create_normal":
        ctx.user_data["gw_type"] = "normal"
        await q.edit_message_text(
            "🎰 *Normal GW Setup*\n\nStep 1/4 — Enter the prize amount (e.g. `$50 USDT`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return GW_AMOUNT

    return ADMIN_MENU


# ── Add / Remove admin ─────────────────────────────────────────────────────────

async def do_add_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("⛔ Only owner can add admins.")
        return ConversationHandler.END
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Send a numeric Telegram user ID.")
        return ADD_ADMIN_ID
    ok = await db.add_admin(target_id, "", uid)
    if ok:
        await update.message.reply_text(f"✅ User `{target_id}` added as admin.",
                                        parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("⚠️ Already an admin.")
    await update.message.reply_text("🛠 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=admin_menu_keyboard(True))
    return ADMIN_MENU


async def do_remove_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("⛔ Only owner can remove admins.")
        return ConversationHandler.END
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return REMOVE_ADMIN_ID
    ok = await db.remove_admin(target_id)
    msg = f"✅ Admin `{target_id}` removed." if ok else "⚠️ Not found in admin list."
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text("🛠 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=admin_menu_keyboard(True))
    return ADMIN_MENU


# ── Giveaway creation flow ─────────────────────────────────────────────────────

async def gw_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        text = "@" + text.lstrip("@")
    ctx.user_data["gw_channel"] = text
    await update.message.reply_text(
        "Step 2/5 — Send the *discussion group link* (e.g. `https://t.me/+abc123`):\n"
        "_(The group where we count messages)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return GW_DISCUSSION


async def gw_discussion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["gw_discussion"] = update.message.text.strip()
    await update.message.reply_text(
        "Step 3/5 — Enter the *prize amount* (e.g. `$100 USDT`):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return GW_AMOUNT


async def gw_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["gw_amount"] = update.message.text.strip()
    gw_type = ctx.user_data.get("gw_type", "normal")
    step = "4/5" if gw_type == "strict" else "2/4"
    await update.message.reply_text(
        f"Step {step} — Enter a *description* (or send `-` to skip):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return GW_DESCRIPTION


async def gw_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    ctx.user_data["gw_description"] = "" if txt == "-" else txt
    gw_type = ctx.user_data.get("gw_type", "normal")
    step = "5/5" if gw_type == "strict" else "3/4"
    await update.message.reply_text(
        f"Step {step} — Enter *duration* in hours (e.g. `24` for 24 hours):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return GW_DURATION


async def gw_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        hours = float(update.message.text.strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number of hours (e.g. `24`).")
        return GW_DURATION

    end_time = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    ctx.user_data["gw_end_time"] = end_time

    gw_type = ctx.user_data.get("gw_type")
    channel = ctx.user_data.get("gw_channel", "N/A")
    discussion = ctx.user_data.get("gw_discussion", "N/A")
    amount = ctx.user_data.get("gw_amount")
    desc = ctx.user_data.get("gw_description") or "—"

    preview = (
        f"✅ *Review Giveaway*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Type: `{gw_type.upper()}`\n"
    )
    if gw_type == "strict":
        preview += f"• Channel: `{channel}`\n• Discussion: {discussion}\n"
    preview += (
        f"• Prize: `{amount}`\n"
        f"• Description: {desc}\n"
        f"• Duration: `{hours}h`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Confirm?"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="gw_confirm"),
         InlineKeyboardButton("❌ Cancel", callback_data="gw_cancel")]
    ])
    await update.message.reply_text(preview, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return GW_CONFIRM


async def gw_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "gw_cancel":
        await q.edit_message_text("❌ Giveaway creation cancelled.")
        return ConversationHandler.END

    uid = q.from_user.id
    gw_type = ctx.user_data["gw_type"]
    data = {
        "type": gw_type,
        "channel": ctx.user_data.get("gw_channel"),
        "discussion_link": ctx.user_data.get("gw_discussion"),
        "amount": ctx.user_data["gw_amount"],
        "description": ctx.user_data.get("gw_description"),
        "end_time": ctx.user_data["gw_end_time"],
        "created_by": uid,
    }
    gw_id = await db.create_giveaway(data)
    ctx.user_data["new_gw_id"] = gw_id

    await q.edit_message_text(
        f"✅ Giveaway *#{gw_id}* created!\n\n"
        f"Now send the *channel or group username* where you want to post it\n"
        f"(e.g. `@MyChannel` or send `here` to post in this chat):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return POST_CHANNEL


async def gw_post_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bot = update.get_bot()
    bot_me = await bot.get_me()
    bot_username = bot_me.username

    gw_id = ctx.user_data["new_gw_id"]
    gw = await db.get_giveaway(gw_id)
    entry_count = await db.get_entry_count(gw_id)
    text, deep_link = build_giveaway_post(gw, entry_count, bot_username)

    txt = update.message.text.strip()
    if txt.lower() == "here":
        target = update.effective_chat.id
    else:
        target = txt if txt.startswith("@") else "@" + txt.lstrip("@")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎉 Participate!", url=deep_link)],
        [InlineKeyboardButton("🔗 Share Giveaway", switch_inline_query=f"gw_{gw_id}")],
    ])

    try:
        msg = await bot.send_message(
            chat_id=target,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
        await db.update_giveaway_post(gw_id, msg.message_id, msg.chat_id)
        await update.message.reply_text(
            f"✅ Giveaway *#{gw_id}* posted!\n"
            f"Entries will update every minute automatically.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to post: {e}")

    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END
