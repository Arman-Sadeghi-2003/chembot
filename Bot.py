import logging
import asyncio
from telegram.ext import Application, MessageHandler, filters, CallbackQueryHandler
from telegram import Update
from config import BOT_TOKEN
import database as db

# Import handlers
from handlers.common import (
    profile_conv, check_membership, reset_bot, cancel, faq, back_to_main,
    show_main_menu, unknown_text
)
from handlers.user_profile import edit_profile_conv
from handlers.user_events import (
    show_events, event_details, register_event, handle_payment_receipt,
    payment_action
)
from handlers.admin_events import (
    add_event_conv, edit_event_conv, toggle_event_conv
)
from handlers.admin_management import (
    admin_menu, announce_conv, manage_admins_conv,
    manual_reg_conv, report_conv
)
from handlers.admin_feedback import (
    feedback_conv, handle_user_rating
)

# تنظیم لاگر
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def main() -> None:
    """راه‌اندازی و اجرای ربات."""
    await db.init_db()  # راه‌اندازی پایگاه داده
    
    # ساخت اپلیکیشن
    app = Application.builder().token(BOT_TOKEN).build()
    
    # --- ثبت Conversation Handlers ---
    app.add_handler(profile_conv)
    app.add_handler(edit_profile_conv)
    app.add_handler(add_event_conv)
    app.add_handler(edit_event_conv)      # هندلر ویرایش جدید
    app.add_handler(toggle_event_conv)
    app.add_handler(announce_conv)
    app.add_handler(manage_admins_conv)
    app.add_handler(manual_reg_conv)
    app.add_handler(report_conv)
    app.add_handler(feedback_conv)        # هندلر نظرسنجی جدید
    
    # --- ثبت Message Handlers ---
    app.add_handler(MessageHandler(filters.Regex("^(دوره‌ها/بازدیدها 📅)$"), show_events))
    app.add_handler(MessageHandler(filters.Regex("^(ارتباط با پشتیبانی 📞)$"), unknown_text))  # TODO: Support handler
    app.add_handler(MessageHandler(filters.Regex("^(سوالات متداول ❓)$"), faq))
    app.add_handler(MessageHandler(filters.Regex("^(منوی ادمین ⚙️)$"), admin_menu))
    app.add_handler(MessageHandler(filters.Regex("^(بازگشت 🔙)$"), back_to_main))
    
    # هندلر رسید پرداخت (باید اولویت کمتری داشته باشد)
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_payment_receipt))
    
    # --- ثبت Callback Query Handlers ---
    app.add_handler(CallbackQueryHandler(check_membership, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(event_details, pattern="^event_"))
    app.add_handler(CallbackQueryHandler(register_event, pattern="^register_"))
    app.add_handler(CallbackQueryHandler(show_events, pattern="^back_to_events$"))
    app.add_handler(CallbackQueryHandler(payment_action, pattern="^(confirm_payment_|unclear_payment_|cancel_payment_|confirm_|done)"))
    app.add_handler(CallbackQueryHandler(handle_user_rating, pattern="^rate_"))  # هندلر امتیازدهی کاربر
    
    logger.info("Bot is starting...")
    
    # استفاده از app.run_polling() بدون asyncio.run()
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        try:
            # Keep the bot running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Bot stopping...")
        finally:
            await app.updater.stop()
            await app.stop()

if __name__ == "__main__":
    # Use nest_asyncio to allow nested event loops if needed
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except RuntimeError as e:
        if "Cannot close a running event loop" in str(e):
            logger.info("Bot stopped")