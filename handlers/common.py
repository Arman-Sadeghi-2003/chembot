# handlers/common.py
import re
import logging
from enum import Enum, auto
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.error import Forbidden
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

import database as db
from config import CHANNEL_ID, ADMIN_IDS

logger = logging.getLogger(__name__)

# --- States ---
class ProfileState(Enum):
    FULL_NAME = auto()
    CONFIRM_FULL_NAME = auto()
    NATIONAL_ID = auto()
    CONFIRM_NATIONAL_ID = auto()
    STUDENT_ID = auto()
    CONFIRM_STUDENT_ID = auto()
    PHONE = auto()
    CONFIRM_PHONE = auto()

# --- Utility Functions ---

def validate_national_id(national_id: str) -> bool:
    if not re.match(r"^\d{10}$", national_id):
        return False
    check = int(national_id[9])
    total = sum(int(national_id[i]) * (10 - i) for i in range(9)) % 11
    return total < 2 and check == total or total >= 2 and check == 11 - total

async def is_user_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    return bool(await db.get_admin_info(user_id))

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        user_id = update.effective_user.id
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Forbidden:
        logger.warning(f"Bot failed to check membership for {user_id}")
        return False
    except Exception as e:
        logger.error(f"Error checking membership for {user_id}: {e}")
        return False

# --- Menu Functions ---

def get_main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        ["دوره‌ها/بازدیدها 📅", "ویرایش مشخصات ✏️"],
        ["ارتباط با پشتیبانی 📞", "سوالات متداول ❓"],
        ["لغو/شروع دوباره 🚪"]
    ]
    if is_admin:
        buttons.insert(-1, ["منوی ادمین ⚙️"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["اضافه کردن رویداد جدید ➕", "ویرایش رویدادها ✏️"],
        ["غیرفعال/فعال کردن رویداد 🔄", "مدیریت ادمین‌ها 👤"],
        ["اعلان عمومی 📢", "گزارش‌ها 📊"],
        ["اضافه کردن دستی به ثبت‌نام 📋", "ارسال نظرسنجی 📊⭐"],
        ["لغو/شروع دوباره 🚪", "بازگشت 🔙"]
    ], resize_keyboard=True)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, full_name: str = None):
    """Helper function to show the main menu."""
    user_id = update.effective_user.id
    if not full_name:
        user_info = await db.get_user_info(user_id)
        full_name = user_info['full_name'] if user_info else "کاربر"
    
    admin_status = await is_user_admin(user_id)
    await update.message.reply_text(
        f"{full_name} عزیز، به ربات انجمن مهندسی شیمی خوش آمدید! 🎉",
        reply_markup=get_main_menu(admin_status)
    )

# --- Basic Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if not await check_channel_membership(update, context):
        await update.message.reply_text(
            f"لطفاً ابتدا کانال رسمی را دنبال کنید: {CHANNEL_ID} 📢",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
            ]])
        )
        return ConversationHandler.END
        
    user_info = await db.get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("لطفاً نام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
        return ProfileState.FULL_NAME
    
    await show_main_menu(update, context, user_info['full_name'])
    return ConversationHandler.END

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if await check_channel_membership(update, context):
        user_id = update.effective_user.id
        user_info = await db.get_user_info(user_id)
        if not user_info:
            await query.message.reply_text("لطفاً نام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
            await query.message.delete()
            return ProfileState.FULL_NAME
        
        await show_main_menu(update, context, user_info['full_name'])
        await query.message.delete()
        return ConversationHandler.END
        
    await query.message.reply_text(
        f"شما هنوز عضو کانال نیستید. لطفاً ابتدا کانال را دنبال کنید: {CHANNEL_ID} 📢",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
        ]])
    )
    return ConversationHandler.END

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Clears user data and restarts the conversation flow."""
    user_id = update.effective_user.id
    context.user_data.clear()
    
    user_info = await db.get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("اطلاعات شما یافت نشد. لطفاً از ابتدا ثبت نام کنید.\nنام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
        return ProfileState.FULL_NAME
        
    await show_main_menu(update, context, user_info['full_name'])
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels any conversation and returns to the main menu."""
    context.user_data.clear()
    await show_main_menu(update, context)
    return ConversationHandler.END

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Returns to main menu, primarily for admin menu."""
    await show_main_menu(update, context)

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "❓ **سوالات متداول**\n\n"
        "1️⃣ **چطور می‌توانم در رویدادها ثبت‌نام کنم؟**\n"
        "از منوی اصلی، گزینه 'دوره‌ها/بازدیدها 📅' را انتخاب کنید...\n\n"
        "2️⃣ **هزینه ثبت‌نام چطور پرداخت می‌شود؟**\n"
        "پس از واریز مبلغ، تصویر رسید را ارسال کنید...\n\n"
        "3️⃣ **چطور می‌توانم پروفایلم را ویرایش کنم؟**\n"
        "از منوی اصلی، گزینه 'ویرایش مشخصات ✏️' را انتخاب کنید...\n\n"
        "4️⃣ **اگر مشکلی داشتم با کجا تماس بگیرم؟**\n"
        "از گزینه 'ارتباط با پشتیبانی 📞' استفاده کنید...\n\n"
        "5️⃣ **چطور می‌توانم از وضعیت ثبت‌نامم مطمئن شوم؟**\n"
        "پس از ثبت‌نام، تأییدیه‌ای دریافت خواهید کرد..."
    )
    await update.message.reply_text(text, reply_markup=get_main_menu(await is_user_admin(update.effective_user.id)))

async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TODO: این تابع باید به تابع پشتیبانی کامل تبدیل شود
    await update.message.reply_text(
        "دستور شما را متوجه نشدم. لطفاً از دکمه‌های منو استفاده کنید. "
        "در صورت نیاز به پشتیبانی، لطفاً منتظر بمانید تا این بخش فعال شود."
    )

# --- Profile Conversation Handler ---
# (این بخش طولانی است و در user_profile.py قرار می‌گیرد)
# اما برای سادگی کار، فعلاً ConversationHandler اصلی ثبت‌نام را اینجا نگه می‌داریم

async def full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if not re.match(r"^[آ-ی\s]{6,}$", text) or text.count(" ") < 1:
        await update.message.reply_text("نام کامل باید حداقل 6 کاراکتر با حروف فارسی و شامل یک فاصله باشد. دوباره وارد کنید:")
        return ProfileState.FULL_NAME
    context.user_data["full_name"] = text
    await update.message.reply_text(
        f"آیا نام زیر درست است؟\n{text}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_full_name"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_full_name")
        ]])
    )
    return ProfileState.CONFIRM_FULL_NAME

async def confirm_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "retry_full_name":
        await query.message.reply_text("لطفاً نام کامل خود را دوباره وارد کنید:")
        await query.message.delete()
        return ProfileState.FULL_NAME
    await query.message.reply_text("لطفاً کد ملی 10 رقمی خود را وارد کنید:")
    await query.message.delete()
    return ProfileState.NATIONAL_ID

async def national_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if not validate_national_id(text):
        await update.message.reply_text("کد ملی نامعتبر است. لطفاً کد ملی 10 رقمی معتبر وارد کنید:")
        return ProfileState.NATIONAL_ID
    context.user_data["national_id"] = text
    await update.message.reply_text(
        f"آیا کد ملی زیر درست است؟\n{text}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_national_id"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_national_id")
        ]])
    )
    return ProfileState.CONFIRM_NATIONAL_ID

async def confirm_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "retry_national_id":
        await query.message.reply_text("لطفاً کد ملی خود را دوباره وارد کنید:")
        await query.message.delete()
        return ProfileState.NATIONAL_ID
    await query.message.reply_text("لطفاً شماره دانشجویی خود را وارد کنید:")
    await query.message.delete()
    return ProfileState.STUDENT_ID

async def student_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if not re.match(r"^\d+$", text):
        await update.message.reply_text("شماره دانشجویی باید فقط شامل اعداد باشد. دوباره وارد کنید:")
        return ProfileState.STUDENT_ID
    context.user_data["student_id"] = text
    await update.message.reply_text(
        f"آیا شماره دانشجویی زیر درست است؟\n{text}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_student_id"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_student_id")
        ]])
    )
    return ProfileState.CONFIRM_STUDENT_ID

async def confirm_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "retry_student_id":
        await query.message.reply_text("لطفاً شماره دانشجویی خود را دوباره وارد کنید:")
        await query.message.delete()
        return ProfileState.STUDENT_ID
    await query.message.reply_text(
        "لطفاً شماره تماس خود را وارد کنید یا دکمه زیر را فشار دهید:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
            one_time_keyboard=True
        )
    )
    await query.message.delete()
    return ProfileState.PHONE

async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.contact:
        phone_num = update.message.contact.phone_number
        phone_num = phone_num.replace("+98", "0") if phone_num.startswith("+98") else phone_num
    else:
        phone_num = update.message.text
        if not re.match(r"^09\d{9}$", phone_num):
            await update.message.reply_text("شماره تماس باید 11 رقم و با 09 شروع شود. دوباره وارد کنید:")
            return ProfileState.PHONE
    context.user_data["phone"] = phone_num
    await update.message.reply_text(
        f"آیا شماره تماس زیر درست است؟\n{phone_num}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_phone"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_phone")
        ]])
    )
    return ProfileState.CONFIRM_PHONE

async def confirm_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "retry_phone":
        await query.message.reply_text(
            "لطفاً شماره تماس خود را دوباره وارد کنید...",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
                one_time_keyboard=True
            )
        )
        await query.message.delete()
        return ProfileState.PHONE
        
    user_id = update.effective_user.id
    try:
        async with await db.get_db_connection() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, full_name, national_id, student_id, phone, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    context.user_data["full_name"],
                    context.user_data["national_id"],
                    context.user_data["student_id"],
                    context.user_data["phone"],
                    datetime.now().isoformat(),
                )
            )
            await conn.commit()
        
        await query.message.reply_text("پروفایل شما با موفقیت ایجاد شد! ✅")
        await show_main_menu(update, context, context.user_data["full_name"])
        await query.message.delete()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error creating profile for {user_id}: {e}")
        await query.message.reply_text("خطایی در ایجاد پروفایل رخ داد. لطفاً دوباره تلاش کنید.")
        return ConversationHandler.END

# --- Conversation Handler Definitions ---
profile_conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^(لغو/شروع دوباره 🚪)$"), reset_bot)
    ],
    states={
        ProfileState.FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name)],
        ProfileState.CONFIRM_FULL_NAME: [CallbackQueryHandler(confirm_full_name, pattern="^(confirm_full_name|retry_full_name)$")],
        ProfileState.NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, national_id)],
        ProfileState.CONFIRM_NATIONAL_ID: [CallbackQueryHandler(confirm_national_id, pattern="^(confirm_national_id|retry_national_id)$")],
        ProfileState.STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_id)],
        ProfileState.CONFIRM_STUDENT_ID: [CallbackQueryHandler(confirm_student_id, pattern="^(confirm_student_id|retry_student_id)$")],
        ProfileState.PHONE: [
            MessageHandler(filters.CONTACT, phone),
            MessageHandler(filters.TEXT & ~filters.COMMAND, phone)
        ],
        ProfileState.CONFIRM_PHONE: [CallbackQueryHandler(confirm_phone, pattern="^(confirm_phone|retry_phone)$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)
