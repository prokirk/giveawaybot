"""Main bot entry point."""
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID   = int(os.getenv("OWNER_ID", "0"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

import database as db
from handlers.admin import (
    admin_panel, admin_callback, do_add_admin, do_remove_admin,
    gw_channel, gw_discussion, gw_amount, gw_description, gw_duration,
    gw_confirm_callback, gw_post_channel, cancel,
    ADMIN_MENU, ADD_ADMIN_ID, REMOVE_ADMIN_ID,
    GW_CHANNEL, GW_DISCUSSION, GW_AMOUNT, GW_DESCRIPTION, GW_DURATION,
    GW_CONFIRM, POST_CHANNEL,
)
from handlers.user import (
    cmd_start, captcha_answer,
    i_shared_callback, confirm_entry_callback,
    CAPTCHA_WAIT, SHARE_WAIT, CONFIRM_WAIT,
)
from handlers.jobs import update_all_posts, track_discussion_messages


# ── Render keep-alive health server ───────────────────────────────────────────
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GW Bot is running!")
    def log_message(self, *args):
        pass

def _start_health():
    port = int(os.getenv("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), _Health).serve_forever()


async def post_init(app: Application):
    await db.init_db()
    logging.getLogger(__name__).info("Database initialised.")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set in .env")

    threading.Thread(target=_start_health, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── Admin conversation ─────────────────────────────────────────────────────
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel)],
        states={
            ADMIN_MENU:      [CallbackQueryHandler(admin_callback)],
            ADD_ADMIN_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, do_add_admin)],
            REMOVE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_remove_admin)],
            GW_CHANNEL:      [MessageHandler(filters.TEXT & ~filters.COMMAND, gw_channel)],
            GW_DISCUSSION:   [MessageHandler(filters.TEXT & ~filters.COMMAND, gw_discussion)],
            GW_AMOUNT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, gw_amount)],
            GW_DESCRIPTION:  [MessageHandler(filters.TEXT & ~filters.COMMAND, gw_description)],
            GW_DURATION:     [MessageHandler(filters.TEXT & ~filters.COMMAND, gw_duration)],
            GW_CONFIRM:      [CallbackQueryHandler(gw_confirm_callback)],
            POST_CHANNEL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, gw_post_channel)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=False,
    )

    # ── User entry conversation ────────────────────────────────────────────────
    # Flow: /start gw_<id> → CAPTCHA_WAIT → SHARE_WAIT → CONFIRM_WAIT → done
    user_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            CAPTCHA_WAIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_answer)
            ],
            SHARE_WAIT: [
                CallbackQueryHandler(i_shared_callback, pattern=r"^i_shared_\d+$")
            ],
            CONFIRM_WAIT: [
                CallbackQueryHandler(confirm_entry_callback, pattern=r"^confirm_entry_\d+$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=False,
        conversation_timeout=1800,  # 30 min — enough time to share
    )

    app.add_handler(admin_conv)
    app.add_handler(user_conv)

    # Track group messages for strict GW message counting
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            track_discussion_messages,
        )
    )

    # Update entry counts and auto-end expired giveaways every 60s
    app.job_queue.run_repeating(update_all_posts, interval=60, first=15)

    logging.getLogger(__name__).info("🤖 GW Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
