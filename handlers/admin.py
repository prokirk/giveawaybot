"""Admin panel conversation handlers."""
from __future__ import annotations
import os
import html
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

import database as db
from formatter import build_giveaway_post

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

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
        [InlineKeyboardButton("⚡ Create Strict GW", callback_data="create_strict"),
         InlineKeyboardButton("🎰 Create Normal GW", callback_data="create_normal")],
        [InlineKeyboardButton("📋 Manage Active Giveaways", callback_data="list_gws_0")],
    ]
    if is_owner:
        kb += [
            [InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
             InlineKeyboardButton("➖ Remove Admin", callback_data="rm_admin")],
            [InlineKeyboardButton("👥 Manage Admins", callback_data="list_admins_0")],
        ]
    kb.append([InlineKeyboardButton("❌ Close Panel", callback_data="close_panel")])
    return InlineKeyboardMarkup(kb)


def paginated_keyboard(callback_prefix: str, page: int, total_items: int, per_page: int = 10, extra_buttons=None):
    kb = extra_buttons or []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{callback_prefix}_{page-1}"))
    if (page + 1) * per_page < total_items:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{callback_prefix}_{page+1}"))
    
    if nav_row:
        kb.append(nav_row)
    kb.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(kb)


async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_owner = uid == OWNER_ID
    if not is_owner and not await db.is_admin(uid):
        await update.message.reply_text("⛔ You don't have admin access.")
        return ConversationHandler.END

    ctx.user_data["is_owner"] = is_owner
    await update.message.reply_text(
        "🛠 <b>Giveaway Admin Dashboard</b>\n\nWelcome! What would you like to do?",
        parse_mode=ParseMode.HTML,
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
        await q.edit_message_text("✅ Admin panel closed.")
        return ConversationHandler.END

    elif data == "back_to_menu":
        await q.edit_message_text(
            "🛠 <b>Giveaway Admin Dashboard</b>\n\nSelect an option:",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu_keyboard(is_owner),
        )
        return ADMIN_MENU

    elif data.startswith("list_admins_"):
        page = int(data.split("_")[-1])
        admins = await db.get_admins()
        if not admins:
            text = "👥 <b>Admins:</b> None added yet."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])
        else:
            per_page = 10
            start = page * per_page
            end = start + per_page
            page_admins = admins[start:end]
            
            lines = []
            for a in page_admins:
                username_part = f" — @{a['username']}" if a.get('username') else ""
                lines.append(f"• <code>{a['user_id']}</code>{html.escape(username_part)}")
                
            text = f"👥 <b>Admins (Page {page+1}):</b>\n" + "\n".join(lines)
            kb = paginated_keyboard("list_admins", page, len(admins), per_page)
            
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADMIN_MENU

    elif data == "add_admin":
        await q.edit_message_text("➕ Enter the numeric Telegram user ID to add as admin:")
        return ADD_ADMIN_ID

    elif data == "rm_admin":
        await q.edit_message_text("➖ Enter the numeric Telegram user ID to remove from admins:")
        return REMOVE_ADMIN_ID

    elif data.startswith("list_gws_"):
        page = int(data.split("_")[-1])
        gws = await db.get_running_giveaways()
        if not gws:
            text = "📋 No active giveaways running."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])
        else:
            per_page = 5
            start = page * per_page
            end = start + per_page
            page_gws = gws[start:end]
            
            text = f"📋 <b>Active Giveaways (Page {page+1})</b>\nSelect one to manage:"
            extra_buttons = []
            for g in page_gws:
                extra_buttons.append([InlineKeyboardButton(
                    f"#{g['id']} [{g['type'].upper()}] - 💰 {g['amount']}", 
                    callback_data=f"manage_gw_{g['id']}"
                )])
                
            kb = paginated_keyboard("list_gws", page, len(gws), per_page, extra_buttons=extra_buttons)
            
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADMIN_MENU

    elif data.startswith("manage_gw_"):
        gw_id = int(data.split("_")[-1])
        gw = await db.get_giveaway(gw_id)
        if not gw or gw['status'] != 'running':
            await q.edit_message_text("❌ Giveaway not found or ended.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="list_gws_0")]]))
            return ADMIN_MENU
            
        text = (
            f"🎯 <b>Manage Giveaway #{gw_id}</b>\n\n"
            f"<b>Type:</b> {gw['type'].upper()}\n"
            f"<b>Channel:</b> {html.escape(gw.get('channel', 'N/A'))}\n"
            f"<b>Prize:</b> {html.escape(gw['amount'])}\n"
            f"<b>Entries:</b> {gw['entry_count']}\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Share Post", switch_inline_query=f"gw_{gw_id}")],
            [InlineKeyboardButton("🗑 Delete Giveaway", callback_data=f"delete_gw_{gw_id}")],
            [InlineKeyboardButton("🔙 Back to List", callback_data="list_gws_0")]
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADMIN_MENU

    elif data.startswith("delete_gw_"):
        gw_id = int(data.split("_")[-1])
        await db.delete_giveaway(gw_id)
        await q.edit_message_text(
            f"🗑 <b>Giveaway #{gw_id} deleted successfully.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to List", callback_data="list_gws_0")]])
        )
        return ADMIN_MENU

    elif data == "create_strict":
        ctx.user_data["gw_type"] = "strict"
        await q.edit_message_text(
            "⚡ <b>Strict GW Setup</b>\n\nStep 1/5 — Send the channel username (e.g. <code>@MyChannel</code>):",
            parse_mode=ParseMode.HTML,
        )
        return GW_CHANNEL

    elif data == "create_normal":
        ctx.user_data["gw_type"] = "normal"
        await q.edit_message_text(
            "🎰 <b>Normal GW Setup</b>\n\nStep 1/4 — Send the channel username (e.g. <code>@MyChannel</code>):\n"
            "<i>(Users must join this channel to participate)</i>",
            parse_mode=ParseMode.HTML,
        )
        return GW_CHANNEL

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
        await update.message.reply_text(f"✅ User <code>{target_id}</code> added as admin.",
                                        parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("⚠️ Already an admin.")
    await update.message.reply_text("🛠 <b>Admin Panel</b>", parse_mode=ParseMode.HTML,
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
    msg = f"✅ Admin <code>{target_id}</code> removed." if ok else "⚠️ Not found in admin list."
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    await update.message.reply_text("🛠 <b>Admin Panel</b>", parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_keyboard(True))
    return ADMIN_MENU


# ── Giveaway creation flow ─────────────────────────────────────────────────────

async def gw_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        text = "@" + text.lstrip("@")
    ctx.user_data["gw_channel"] = text
    gw_type = ctx.user_data.get("gw_type", "normal")
    if gw_type == "strict":
        await update.message.reply_text(
            "Step 2/5 — Send the <b>discussion group link</b> (e.g. <code>https://t.me/+abc123</code>):\n"
            "<i>(The group where we count messages for top-texter selection)</i>",
            parse_mode=ParseMode.HTML,
        )
        return GW_DISCUSSION
    else:
        # Normal GW — skip discussion, go straight to amount
        await update.message.reply_text(
            "Step 2/4 — Enter the <b>prize amount</b> (e.g. <code>$50 USDT</code>):",
            parse_mode=ParseMode.HTML,
        )
        return GW_AMOUNT


async def gw_discussion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["gw_discussion"] = update.message.text.strip()
    await update.message.reply_text(
        "Step 3/5 — Enter the <b>prize amount</b> (e.g. <code>$100 USDT</code>):",
        parse_mode=ParseMode.HTML,
    )
    return GW_AMOUNT


async def gw_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["gw_amount"] = update.message.text.strip()
    gw_type = ctx.user_data.get("gw_type", "normal")
    step = "4/5" if gw_type == "strict" else "3/4"
    await update.message.reply_text(
        f"Step {step} — Enter a <b>description</b> (or send <code>-</code> to skip):",
        parse_mode=ParseMode.HTML,
    )
    return GW_DESCRIPTION


async def gw_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    ctx.user_data["gw_description"] = "" if txt == "-" else txt
    gw_type = ctx.user_data.get("gw_type", "normal")
    step = "5/5" if gw_type == "strict" else "4/4"
    await update.message.reply_text(
        f"Step {step} — Enter <b>duration</b> in hours (e.g. <code>24</code> for 24 hours):",
        parse_mode=ParseMode.HTML,
    )
    return GW_DURATION


async def gw_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        hours = float(update.message.text.strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number of hours (e.g. <code>24</code>).", parse_mode=ParseMode.HTML)
        return GW_DURATION

    end_time = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    ctx.user_data["gw_end_time"] = end_time

    gw_type = ctx.user_data.get("gw_type")
    channel = ctx.user_data.get("gw_channel", "N/A")
    discussion = ctx.user_data.get("gw_discussion", "N/A")
    amount = ctx.user_data.get("gw_amount")
    desc = ctx.user_data.get("gw_description") or "—"

    preview = (
        f"✅ <b>Review Giveaway</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Type:</b> <code>{gw_type.upper()}</code>\n"
        f"• <b>Channel:</b> <code>{html.escape(channel)}</code>\n"
    )
    if gw_type == "strict":
        preview += f"• <b>Discussion:</b> {html.escape(discussion)}\n"
    preview += (
        f"• <b>Prize:</b> <code>{html.escape(amount)}</code>\n"
        f"• <b>Description:</b> {html.escape(desc)}\n"
        f"• <b>Duration:</b> <code>{hours}h</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Confirm?"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Create", callback_data="gw_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="gw_cancel")]
    ])
    await update.message.reply_text(preview, parse_mode=ParseMode.HTML, reply_markup=kb)
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
        f"✅ <b>Giveaway #{gw_id} created!</b>\n\n"
        f"⚠️ <b>Important:</b> To automatically update the live entry count on the post, "
        f"the bot MUST be the one who sends it to the channel.\n\n"
        f"1️⃣ First, add this bot as an <b>Admin</b> in your target channel.\n"
        f"2️⃣ Then, send the channel username here (e.g. <code>@MyChannel</code> or send <code>here</code> to post in this chat):",
        parse_mode=ParseMode.HTML,
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
            f"✅ Giveaway <b>#{gw_id}</b> posted successfully!\n"
            f"Entries will update every minute automatically.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to post: <code>{e}</code>\n\n"
            f"You can try sharing it manually from the <b>Manage Active Giveaways</b> menu.",
            parse_mode=ParseMode.HTML
        )

    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END
