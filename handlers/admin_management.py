# handlers/admin_management.py
import re
import logging
from enum import Enum, auto
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    MessageHandler, CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

import database as db
from config import OPERATOR_GROUP_ID
from handlers.common import get_admin_menu, cancel, is_user_admin
from handlers.user_events import deactivate_event # Import for manual reg capacity check

logger = logging.getLogger(__name__)

# --- States ---
class AnnounceState(Enum):
    CHOOSE_GROUP = auto()
    GET_MESSAGE = auto()

class AdminManageState(Enum):
    CHOOSE_ACTION = auto()
    GET_ID_TO_ADD = auto()
    CHOOSE_TO_REMOVE = auto()

class ManualRegState(Enum):
    CHOOSE_EVENT = auto()
    GET_STUDENT_ID = auto()
    CONFIRM = auto()

class ReportState(Enum):
    CHOOSE_TYPE = auto()
    CHOOSE_PERIOD_OR_EVENT = auto()

# --- Admin Menu Entry ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_admin(update.effective_user.id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return
    await update.message.reply_text("منوی ادمین:", reply_markup=get_admin_menu())

# --- 1. Announce Conversation ---
async def announce_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_user_admin(update.effective_user.id):
        return ConversationHandler.END
        
    events = await db.get_all_events()
    buttons = [[InlineKeyboardButton(f"{event['title']} ({event['type']})", callback_data=f"announce_group_{event['event_id']}")] for event in events]
    buttons.append([InlineKeyboardButton("همه کاربران", callback_data="announce_group_all")])
    
    await update.message.reply_text("گروه هدف اعلان را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return AnnounceState.CHOOSE_GROUP

async def announce_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_data = query.data.split("announce_group_")[1]
    context.user_data["announce_group"] = group_data
    await query.message.edit_text("لطفاً متن اعلان را وارد کنید:")
    return AnnounceState.GET_MESSAGE

async def send_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for send_announcement remains the same as your optimized code) ...
    # ... (Remember to add asyncio.sleep(0.1) in the loop) ...
    await update.message.reply_text("اعلان با موفقیت ارسال شد! ✅", reply_markup=get_admin_menu())
    return ConversationHandler.END

announce_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(اعلان عمومی 📢)$"), announce_start)],
    states={
        AnnounceState.CHOOSE_GROUP: [CallbackQueryHandler(announce_group, pattern="^announce_group_")],
        AnnounceState.GET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_announcement)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)


# --- 2. Manage Admins Conversation ---
async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for manage_admins remains the same) ...
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("اضافه کردن ادمین ➕", callback_data="add_admin")],
            [InlineKeyboardButton("حذف ادمین ➖", callback_data="remove_admin")]
        ])
    )
    return AdminManageState.CHOOSE_ACTION

async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.message.edit_text("لطفاً آیدی عددی ادمین جدید را وارد کنید:")
    return AdminManageState.GET_ID_TO_ADD

async def remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for remove_admin_start remains the same) ...
    await update.callback_query.message.edit_text("ادمین را برای حذف انتخاب کنید:")
    return AdminManageState.CHOOSE_TO_REMOVE

async def save_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for save_admin remains the same) ...
    await update.message.reply_text("ادمین با موفقیت اضافه شد! ✅", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for remove_admin remains the same) ...
    await update.callback_query.message.edit_text("ادمین با موفقیت حذف شد! ✅", reply_markup=get_admin_menu())
    return ConversationHandler.END

manage_admins_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(مدیریت ادمین‌ها 👤)$"), manage_admins)],
    states={
        AdminManageState.CHOOSE_ACTION: [
            CallbackQueryHandler(add_admin_start, pattern="^add_admin$"),
            CallbackQueryHandler(remove_admin_start, pattern="^remove_admin$"),
        ],
        AdminManageState.GET_ID_TO_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_admin)],
        AdminManageState.CHOOSE_TO_REMOVE: [CallbackQueryHandler(remove_admin, pattern="^remove_")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)


# --- 3. Manual Registration Conversation ---
async def manual_registration_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for manual_registration_start remains the same) ...
    await update.message.reply_text("رویداد را انتخاب کنید:")
    return ManualRegState.CHOOSE_EVENT

async def manual_registration_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for manual_registration_event remains the same) ...
    await update.callback_query.message.edit_text("لطفاً شماره دانشجویی کاربر را وارد کنید:")
    return ManualRegState.GET_STUDENT_ID

async def manual_registration_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for manual_registration_student_id remains the same) ...
    await update.message.reply_text("آیا ثبت‌نام کاربر زیر را تأیید می‌کنید؟\n...")
    return ManualRegState.CONFIRM

async def confirm_manual_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for confirm_manual_registration remains the same) ...
    # ... (Ensure it calls deactivate_event if capacity is full) ...
    await update.callback_query.message.edit_text("ثبت‌نام دستی با موفقیت انجام شد! ✅", reply_markup=get_admin_menu())
    return ConversationHandler.END

manual_reg_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(اضافه کردن دستی به ثبت‌نام 📋)$"), manual_registration_start)],
    states={
        ManualRegState.CHOOSE_EVENT: [CallbackQueryHandler(manual_registration_event, pattern="^manual_reg_")],
        ManualRegState.GET_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_registration_student_id)],
        ManualRegState.CONFIRM: [CallbackQueryHandler(confirm_manual_registration, pattern="^(confirm_manual_reg|cancel_manual_reg)$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)

# --- 4. Reports Conversation ---
async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for report_start remains the same) ...
    await update.message.reply_text("نوع گزارش را انتخاب کنید:")
    return ReportState.CHOOSE_TYPE

async def report_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for report_type remains the same) ...
    await update.callback_query.message.edit_text("رویداد یا بازه زمانی را انتخاب کنید:")
    return ReportState.CHOOSE_PERIOD_OR_EVENT

async def generate_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Logic for generate_report remains the same) ...
    await update.callback_query.message.edit_text("گزارش شما:\n...", reply_markup=get_admin_menu())
    return ConversationHandler.END

report_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(گزارش‌ها 📊)$"), report_start)],
    states={
        ReportState.CHOOSE_TYPE: [CallbackQueryHandler(report_type, pattern="^report_")],
        ReportState.CHOOSE_PERIOD_OR_EVENT: [CallbackQueryHandler(generate_report, pattern="^(report_event_|period_)")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)
