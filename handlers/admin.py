"""Admin panel conversation handlers."""
from __future__ import annotations
import os
import html
from datetime import datetime, timedelta, timezone
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
    GW_CHANNEL, GW_DISCUSSION, GW_AMOUNT, GW_DESCRIPTION, GW_DURATION, GW_IMAGE,
    GW_CONFIRM,
    POST_CHANNEL,
) = range(12)


def owner_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Create Strict GW",  callback_data="create_strict"),
         InlineKeyboardButton("Create Normal GW",  callback_data="create_normal")],
        [InlineKeyboardButton("Active Giveaways",  callback_data="list_gws_0")],
        [InlineKeyboardButton("Add Admin",         callback_data="add_admin"),
         InlineKeyboardButton("Remove Admin",      callback_data="rm_admin")],
        [InlineKeyboardButton("Manage Admins",     callback_data="list_admins_0")],
        [InlineKeyboardButton("Close",             callback_data="close_panel")],
    ])


def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Create Strict GW",  callback_data="create_strict"),
         InlineKeyboardButton("Create Normal GW",  callback_data="create_normal")],
        [InlineKeyboardButton("My Giveaways",      callback_data="list_gws_0")],
        [InlineKeyboardButton("Close",             callback_data="close_panel")],
    ])


def paginated_keyboard(prefix: str, page: int, total: int, per_page: int = 5, extra=None):
    kb = extra or []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"{prefix}_{page-1}"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton("Next", callback_data=f"{prefix}_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("Back", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(kb)


# ── Entry points ───────────────────────────────────────────────────────────────

async def owner_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point for /owner — owner only."""
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    ctx.user_data["is_owner"] = True
    await update.message.reply_text(
        "<b>Owner Panel</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=owner_menu_keyboard(),
    )
    return ADMIN_MENU


async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point for /admin — admins only (restricted view)."""
    uid      = update.effective_user.id
    is_owner = uid == OWNER_ID
    if not is_owner and not await db.is_admin(uid):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    if is_owner:
        ctx.user_data["is_owner"] = True
        await update.message.reply_text(
            "<b>Owner Panel</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=owner_menu_keyboard(),
        )
    else:
        ctx.user_data["is_owner"] = False
        await update.message.reply_text(
            "<b>Admin Panel</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu_keyboard(),
        )
    return ADMIN_MENU


# ── Shared callback router ─────────────────────────────────────────────────────

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q        = update.callback_query
    await q.answer()
    data     = q.data
    uid      = q.from_user.id
    is_owner = uid == OWNER_ID or ctx.user_data.get("is_owner", False)

    if not is_owner and not await db.is_admin(uid):
        await q.edit_message_text("Access denied.")
        return ConversationHandler.END

    if data == "close_panel":
        await q.edit_message_text("Panel closed.")
        return ConversationHandler.END

    if data == "back_to_menu":
        if is_owner:
            await q.edit_message_text(
                "<b>Owner Panel</b>", parse_mode=ParseMode.HTML,
                reply_markup=owner_menu_keyboard(),
            )
        else:
            await q.edit_message_text(
                "<b>Admin Panel</b>", parse_mode=ParseMode.HTML,
                reply_markup=admin_menu_keyboard(),
            )
        return ADMIN_MENU

    # ── List admins (owner only) ───────────────────────────────────────────────
    if data.startswith("list_admins_"):
        if not is_owner:
            await q.answer("Owner only.", show_alert=True)
            return ADMIN_MENU
        page    = int(data.split("_")[-1])
        admins  = await db.get_admins()
        if not admins:
            text = "<b>Admins:</b> None added yet."
            kb   = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_to_menu")]])
        else:
            per_page = 10
            start    = page * per_page
            page_admins = admins[start:start + per_page]
            lines = []
            for a in page_admins:
                uname = f" — @{a['username']}" if a.get("username") else ""
                lines.append(f"<code>{a['user_id']}</code>{html.escape(uname)}")
            text = f"<b>Admins (page {page+1}):</b>\n" + "\n".join(lines)
            kb   = paginated_keyboard("list_admins", page, len(admins), 10)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADMIN_MENU

    # ── Add / remove admin (owner only) ───────────────────────────────────────
    if data == "add_admin":
        if not is_owner:
            await q.answer("Owner only.", show_alert=True)
            return ADMIN_MENU
        await q.edit_message_text("Enter the numeric Telegram user ID to add as admin:")
        return ADD_ADMIN_ID

    if data == "rm_admin":
        if not is_owner:
            await q.answer("Owner only.", show_alert=True)
            return ADMIN_MENU
        await q.edit_message_text("Enter the numeric Telegram user ID to remove:")
        return REMOVE_ADMIN_ID

    # ── List giveaways ─────────────────────────────────────────────────────────
    if data.startswith("list_gws_"):
        page = int(data.split("_")[-1])
        if is_owner:
            gws = await db.get_running_giveaways()
        else:
            gws = await db.get_running_giveaways_by_user(uid)
        if not gws:
            text = "No active giveaways."
            kb   = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_to_menu")]])
        else:
            per_page    = 5
            start       = page * per_page
            page_gws    = gws[start:start + per_page]
            text        = f"<b>Active Giveaways (page {page+1})</b>"
            extra_btns  = []
            for g in page_gws:
                label = f"#{g['id']} [{g['type'].upper()}] — {g['amount']}"
                extra_btns.append([InlineKeyboardButton(label, callback_data=f"manage_gw_{g['id']}")])
            kb = paginated_keyboard("list_gws", page, len(gws), per_page, extra=extra_btns)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADMIN_MENU

    # ── Manage single GW ───────────────────────────────────────────────────────
    if data.startswith("manage_gw_"):
        gw_id = int(data.split("_")[-1])
        gw    = await db.get_giveaway(gw_id)
        if not gw or gw["status"] != "running":
            await q.edit_message_text(
                "Giveaway not found or ended.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="list_gws_0")]])
            )
            return ADMIN_MENU
        # Non-owners can only manage their own GWs
        if not is_owner and gw.get("created_by") != uid:
            await q.answer("You can only manage your own giveaways.", show_alert=True)
            return ADMIN_MENU
        text = (
            f"<b>Giveaway #{gw_id}</b>\n\n"
            f"Type: {gw['type'].upper()}\n"
            f"Channel: {html.escape(gw.get('channel') or 'N/A')}\n"
            f"Prize: {html.escape(gw['amount'])}\n"
            f"Entries: {gw['entry_count']}\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Share",  switch_inline_query=f"gw_{gw_id}")],
            [InlineKeyboardButton("Delete", callback_data=f"delete_gw_{gw_id}")],
            [InlineKeyboardButton("Back",   callback_data="list_gws_0")],
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADMIN_MENU

    # ── Delete GW ──────────────────────────────────────────────────────────────
    if data.startswith("delete_gw_"):
        gw_id = int(data.split("_")[-1])
        gw    = await db.get_giveaway(gw_id)
        if gw and not is_owner and gw.get("created_by") != uid:
            await q.answer("You can only delete your own giveaways.", show_alert=True)
            return ADMIN_MENU
        await db.delete_giveaway(gw_id)
        await q.edit_message_text(
            f"Giveaway #{gw_id} deleted.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="list_gws_0")]])
        )
        return ADMIN_MENU

    # ── GW type selection ──────────────────────────────────────────────────────
    if data == "create_strict":
        ctx.user_data["gw_type"] = "strict"
        await q.edit_message_text(
            "<b>Strict GW — Step 1/5</b>\n\nSend the channel username (e.g. <code>@MyChannel</code>):",
            parse_mode=ParseMode.HTML,
        )
        return GW_CHANNEL

    if data == "create_normal":
        ctx.user_data["gw_type"] = "normal"
        await q.edit_message_text(
            "<b>Normal GW — Step 1/4</b>\n\nSend the channel username (e.g. <code>@MyChannel</code>):",
            parse_mode=ParseMode.HTML,
        )
        return GW_CHANNEL

    return ADMIN_MENU


# ── Add / Remove admin ─────────────────────────────────────────────────────────

async def do_add_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Only the owner can add admins.")
        return ConversationHandler.END
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid ID. Send a numeric Telegram user ID.")
        return ADD_ADMIN_ID
    ok = await db.add_admin(target_id, "", uid)
    msg = f"User <code>{target_id}</code> added as admin." if ok else "Already an admin."
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    await update.message.reply_text(
        "<b>Owner Panel</b>", parse_mode=ParseMode.HTML,
        reply_markup=owner_menu_keyboard()
    )
    return ADMIN_MENU


async def do_remove_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Only the owner can remove admins.")
        return ConversationHandler.END
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid ID.")
        return REMOVE_ADMIN_ID
    ok  = await db.remove_admin(target_id)
    msg = f"Admin <code>{target_id}</code> removed." if ok else "Not found in admin list."
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    await update.message.reply_text(
        "<b>Owner Panel</b>", parse_mode=ParseMode.HTML,
        reply_markup=owner_menu_keyboard()
    )
    return ADMIN_MENU


# ── Giveaway creation flow ─────────────────────────────────────────────────────

async def gw_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        text = "@" + text.lstrip("@")
    ctx.user_data["gw_channel"] = text
    if ctx.user_data.get("gw_type") == "strict":
        await update.message.reply_text(
            "Step 2/5 — Send the <b>discussion group link</b> (e.g. <code>https://t.me/+abc123</code>):",
            parse_mode=ParseMode.HTML,
        )
        return GW_DISCUSSION
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
    step = "4/5" if ctx.user_data.get("gw_type") == "strict" else "3/4"
    await update.message.reply_text(
        f"Step {step} — Enter a <b>description</b> (or <code>-</code> to skip):",
        parse_mode=ParseMode.HTML,
    )
    return GW_DESCRIPTION


async def gw_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    ctx.user_data["gw_description"] = "" if txt == "-" else txt
    step = "5/5" if ctx.user_data.get("gw_type") == "strict" else "4/4"
    await update.message.reply_text(
        f"Step {step} — Enter <b>duration</b> in hours (e.g. <code>24</code>):",
        parse_mode=ParseMode.HTML,
    )
    return GW_DURATION


async def gw_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        hours = float(update.message.text.strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Enter a valid number of hours (e.g. <code>24</code>).",
            parse_mode=ParseMode.HTML
        )
        return GW_DURATION

    end_time = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    ctx.user_data["gw_end_time"] = end_time
    ctx.user_data["gw_hours"] = hours

    step = "6/6" if ctx.user_data.get("gw_type") == "strict" else "5/5"
    await update.message.reply_text(
        f"Step {step} — <b>Send an image</b> for the giveaway, or send <code>-</code> to skip:",
        parse_mode=ParseMode.HTML,
    )
    return GW_IMAGE


async def gw_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        ctx.user_data["gw_image_id"] = update.message.photo[-1].file_id
    else:
        ctx.user_data["gw_image_id"] = None

    hours      = ctx.user_data["gw_hours"]
    gw_type    = ctx.user_data.get("gw_type")
    channel    = ctx.user_data.get("gw_channel", "N/A")
    discussion = ctx.user_data.get("gw_discussion", "N/A")
    amount     = ctx.user_data.get("gw_amount")
    desc       = ctx.user_data.get("gw_description") or "—"

    preview = (
        f"<b>Review</b>\n\n"
        f"Type: <code>{gw_type.upper()}</code>\n"
        f"Channel: <code>{html.escape(channel)}</code>\n"
    )
    if gw_type == "strict":
        preview += f"Discussion: {html.escape(discussion)}\n"
    preview += (
        f"Prize: <code>{html.escape(amount)}</code>\n"
        f"Description: {html.escape(desc)}\n"
        f"Duration: <code>{hours}h</code>\n"
        f"Image: {'Yes' if ctx.user_data.get('gw_image_id') else 'No'}\n"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Confirm", callback_data="gw_confirm"),
         InlineKeyboardButton("Cancel",  callback_data="gw_cancel")],
    ])
    await update.message.reply_text(preview, parse_mode=ParseMode.HTML, reply_markup=kb)
    return GW_CONFIRM


async def gw_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "gw_cancel":
        await q.edit_message_text("Cancelled.")
        return ConversationHandler.END

    uid  = q.from_user.id
    data = {
        "type":            ctx.user_data["gw_type"],
        "channel":         ctx.user_data.get("gw_channel"),
        "discussion_link": ctx.user_data.get("gw_discussion"),
        "amount":          ctx.user_data["gw_amount"],
        "description":     ctx.user_data.get("gw_description"),
        "end_time":        ctx.user_data["gw_end_time"],
        "created_by":      uid,
        "image_id":        ctx.user_data.get("gw_image_id"),
    }
    gw_id = await db.create_giveaway(data)
    ctx.user_data["new_gw_id"] = gw_id

    await q.edit_message_text(
        f"<b>Giveaway #{gw_id} created!</b>\n\n"
        f"Add this bot as Admin in your target channel, then send the channel username "
        f"(e.g. <code>@MyChannel</code>) or <code>here</code> to post in this chat:",
        parse_mode=ParseMode.HTML,
    )
    return POST_CHANNEL


async def gw_post_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bot          = update.get_bot()
    bot_me       = await bot.get_me()
    gw_id        = ctx.user_data["new_gw_id"]
    gw           = await db.get_giveaway(gw_id)
    entry_count  = await db.get_entry_count(gw_id)
    text, deep_link = build_giveaway_post(gw, entry_count, bot_me.username)

    txt    = update.message.text.strip()
    target = update.effective_chat.id if txt.lower() == "here" else (
        txt if txt.startswith("@") else "@" + txt.lstrip("@")
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Participate!", url=deep_link)],
        [InlineKeyboardButton("Share",        switch_inline_query=f"gw_{gw_id}")],
    ])

    try:
        if gw.get("image_id"):
            msg = await bot.send_photo(
                chat_id=target, photo=gw["image_id"], caption=text,
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
            )
        else:
            msg = await bot.send_message(
                chat_id=target, text=text,
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
            )
        await db.update_giveaway_post(gw_id, msg.message_id, msg.chat_id)
        await update.message.reply_text(
            f"Giveaway <b>#{gw_id}</b> posted. Entries update every minute.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(
            f"Failed to post: <code>{e}</code>\n\nShare manually from Manage Giveaways.",
            parse_mode=ParseMode.HTML,
        )
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END
