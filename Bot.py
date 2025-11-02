import os
import re
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram import Update

# تنظیم لاگر اصلی
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO # تغییر به INFO برای دیدن لاگ‌های بیشتر در صورت نیاز
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Bot configuration
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# !!! توکن ربات جدید خود را در اینجا قرار دهید !!!
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
BOT_TOKEN = "YOUR_NEW_BOT_TOKEN_HERE" 
DB_PATH = "jahad_bot.db" # نام پایگاه داده جدید

def init_db():
    """ایجاد جدول کاربران در پایگاه داده"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                national_id TEXT,
                student_id TEXT,
                phone TEXT,
                created_at TEXT
            )
        """)
        conn.commit()

# States for conversation handlers
# فقط استیت‌های مربوط به ثبت‌نام و ویرایش پروفایل نگهداری شده‌اند
FULL_NAME, CONFIRM_FULL_NAME, NATIONAL_ID, CONFIRM_NATIONAL_ID, STUDENT_ID, CONFIRM_STUDENT_ID, PHONE, CONFIRM_PHONE = range(8)
EDIT_PROFILE, EDIT_PROFILE_VALUE = range(2)

# Utility functions
def validate_national_id(national_id: str) -> bool:
    """اعتبارسنجی کد ملی"""
    if not re.match(r"^\d{10}$", national_id):
        return False
    check = int(national_id[9])
    total = sum(int(national_id[i]) * (10 - i) for i in range(9)) % 11
    return total < 2 and check == total or total >= 2 and check == 11 - total

def get_user_info(user_id: int) -> tuple:
    """دریافت اطلاعات کاربر از پایگاه داده"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return c.fetchone()

def get_main_menu() -> ReplyKeyboardMarkup:
    """ایجاد منوی اصلی ساده شده"""
    buttons = [
        ["ویرایش مشخصات ✏️"],
        ["لغو/شروع دوباره 🚪"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع کار ربات و بررسی وضعیت ثبت‌نام کاربر"""
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    
    if not user_info:
        # کاربر جدید
        await update.message.reply_text("سلام! به ربات جهاد دانشگاهی خوش آمدید. 🌷\n\nبرای استفاده از امکانات ربات، لطفاً ابتدا ثبت‌نام کنید.")
        await update.message.reply_text("لطفاً نام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
        return FULL_NAME
    
    # کاربر قبلاً ثبت‌نام کرده
    full_name = user_info[1]
    await update.message.reply_text(
        f"{full_name} عزیز، به ربات جهاد دانشگاهی خوش آمدید! 🎉",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END

async def full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام کامل"""
    text = update.message.text
    if not re.match(r"^[آ-ی\s]{6,}$", text) or text.count(" ") < 1:
        await update.message.reply_text("نام کامل باید حداقل 6 کاراکتر با حروف فارسی و شامل یک فاصله باشد. دوباره وارد کنید:")
        return FULL_NAME
    context.user_data["full_name"] = text
    await update.message.reply_text(
        f"آیا نام زیر درست است؟\n{text}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_full_name"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_full_name")
        ]])
    )
    return CONFIRM_FULL_NAME

async def confirm_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تأیید نام کامل"""
    query = update.callback_query
    await query.answer()
    if query.data == "retry_full_name":
        await query.message.reply_text("لطفاً نام کامل خود را دوباره وارد کنید:")
        await query.message.delete()
        return FULL_NAME
    await query.message.reply_text("لطفاً کد ملی 10 رقمی خود را وارد کنید:")
    await query.message.delete()
    return NATIONAL_ID

async def national_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت کد ملی"""
    text = update.message.text
    if not validate_national_id(text):
        await update.message.reply_text("کد ملی نامعتبر است. لطفاً کد ملی 10 رقمی معتبر وارد کنید:")
        return NATIONAL_ID
    context.user_data["national_id"] = text
    await update.message.reply_text(
        f"آیا کد ملی زیر درست است؟\n{text}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_national_id"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_national_id")
        ]])
    )
    return CONFIRM_NATIONAL_ID

async def confirm_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تأیید کد ملی"""
    query = update.callback_query
    await query.answer()
    if query.data == "retry_national_id":
        await query.message.reply_text("لطفاً کد ملی خود را دوباره وارد کنید:")
        await query.message.delete()
        return NATIONAL_ID
    await query.message.reply_text("لطفاً شماره دانشجویی خود را وارد کنید:")
    await query.message.delete()
    return STUDENT_ID

async def student_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت شماره دانشجویی"""
    text = update.message.text
    if not re.match(r"^\d+$", text):
        await update.message.reply_text("شماره دانشجویی باید فقط شامل اعداد باشد. دوباره وارد کنید:")
        return STUDENT_ID
    context.user_data["student_id"] = text
    await update.message.reply_text(
        f"آیا شماره دانشجویی زیر درست است؟\n{text}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_student_id"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_student_id")
        ]])
    )
    return CONFIRM_STUDENT_ID

async def confirm_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تأیید شماره دانشجویی"""
    query = update.callback_query
    await query.answer()
    if query.data == "retry_student_id":
        await query.message.reply_text("لطفاً شماره دانشجویی خود را دوباره وارد کنید:")
        await query.message.delete()
        return STUDENT_ID
    await query.message.reply_text(
        "لطفاً شماره تماس خود را وارد کنید یا دکمه زیر را فشار دهید:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
            one_time_keyboard=True,
            resize_keyboard=True
        )
    )
    await query.message.delete()
    return PHONE

async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت شماره تلفن"""
    if update.message.contact:
        phone = update.message.contact.phone_number
        phone = phone.replace("+98", "0") if phone.startswith("+98") else phone
    else:
        phone = update.message.text
        if not re.match(r"^09\d{9}$", phone):
            await update.message.reply_text("شماره تماس باید 11 رقم و با 09 شروع شود. دوباره وارد کنید:")
            return PHONE
    context.user_data["phone"] = phone
    await update.message.reply_text(
        f"آیا شماره تماس زیر درست است؟\n{phone}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("بله ✅", callback_data="confirm_phone"),
            InlineKeyboardButton("خیر ✏️", callback_data="retry_phone")
        ]])
    )
    return CONFIRM_PHONE

async def confirm_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تأیید نهایی و ذخیره کاربر"""
    query = update.callback_query
    await query.answer()
    if query.data == "retry_phone":
        await query.message.reply_text(
            "لطفاً شماره تماس خود را دوباره وارد کنید یا دکمه زیر را فشار دهید:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
        await query.message.delete()
        return PHONE
        
    user_id = update.effective_user.id
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
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
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}")
        await query.message.reply_text("خطایی در ذخیره اطلاعات رخ داد. لطفاً /start را دوباره بزنید.")
        return ConversationHandler.END

    await query.message.reply_text(
        "پروفایل شما با موفقیت ایجاد شد! ✅",
        reply_markup=get_main_menu()
    )
    await query.message.delete()
    return ConversationHandler.END

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ریست کردن ربات و بازگشت به منوی اصلی"""
    user_id = update.effective_user.id
    context.user_data.clear()  # پاک کردن تمام داده‌های موقت
    user_info = get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("ثبت‌نام شما کامل نشده است. لطفاً /start را بزنید.")
        return ConversationHandler.END
    
    full_name = user_info[1]
    await update.message.reply_text(
        f"{full_name} عزیز، به منوی اصلی بازگشتید.",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END

async def edit_profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع فرآیند ویرایش پروفایل"""
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    
    if not user_info:
        await update.message.reply_text("ابتدا پروفایل خود را تکمیل کنید! لطفاً /start را بزنید.", reply_markup=get_main_menu())
        return ConversationHandler.END
        
    text = (
        f"اطلاعات فعلی شما:\n"
        f"نام کامل: {user_info[1]}\n"
        f"کد ملی: {user_info[2]}\n"
        f"شماره دانشجویی: {user_info[3]}\n"
        f"شماره تماس: {user_info[4]}"
    )
    buttons = [
        [InlineKeyboardButton("ویرایش نام ✏️", callback_data="edit_full_name")],
        [InlineKeyboardButton("ویرایش کد ملی ✏️", callback_data="edit_national_id")],
        [InlineKeyboardButton("ویرایش شماره دانشجویی ✏️", callback_data="edit_student_id")],
        [InlineKeyboardButton("ویرایش شماره تماس ✏️", callback_data="edit_phone")],
        [InlineKeyboardButton("لغو 🚫", callback_data="cancel_edit")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return EDIT_PROFILE

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """انتخاب فیلد برای ویرایش"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if query.data == "cancel_edit":
        await query.message.reply_text("ویرایش لغو شد.", reply_markup=get_main_menu())
        await query.message.delete()
        return ConversationHandler.END
        
    context.user_data["edit_field"] = query.data
    field_name_map = {
        "edit_full_name": "نام کامل",
        "edit_national_id": "کد ملی",
        "edit_student_id": "شماره دانشجویی",
        "edit_phone": "شماره تماس"
    }
    field_name = field_name_map.get(query.data, "فیلد")
    
    if query.data == "edit_phone":
        await query.message.reply_text(
            f"لطفاً {field_name} جدید را وارد کنید یا دکمه زیر را فشار دهید:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
    else:
        await query.message.reply_text(f"لطفاً {field_name} جدید را وارد کنید:")
    await query.message.delete()
    return EDIT_PROFILE_VALUE

async def edit_profile_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت و ذخیره مقدار جدید برای فیلد انتخابی"""
    user_id = update.effective_user.id
    field = context.user_data.get("edit_field")
    if not field:
        await update.message.reply_text("خطایی رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=get_main_menu())
        return ConversationHandler.END

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if field == "edit_full_name":
            text = update.message.text
            if not re.match(r"^[آ-ی\s]{6,}$", text) or text.count(" ") < 1:
                await update.message.reply_text("نام کامل باید حداقل 6 کاراکتر با حروف فارسی و شامل یک فاصله باشد. دوباره وارد کنید:")
                return EDIT_PROFILE_VALUE
            c.execute("UPDATE users SET full_name = ? WHERE user_id = ?", (text, user_id))
        elif field == "edit_national_id":
            text = update.message.text
            if not validate_national_id(text):
                await update.message.reply_text("کد ملی نامعتبر است. لطفاً کد ملی 10 رقمی معتبر وارد کنید:")
                return EDIT_PROFILE_VALUE
            c.execute("UPDATE users SET national_id = ? WHERE user_id = ?", (text, user_id))
        elif field == "edit_student_id":
            text = update.message.text
            if not re.match(r"^\d+$", text):
                await update.message.reply_text("شماره دانشجویی باید فقط شامل اعداد باشد. دوباره وارد کنید:")
                return EDIT_PROFILE_VALUE
            c.execute("UPDATE users SET student_id = ? WHERE user_id = ?", (text, user_id))
        elif field == "edit_phone":
            if update.message.contact:
                phone = update.message.contact.phone_number
                phone = phone.replace("+98", "0") if phone.startswith("+98") else phone
            else:
                phone = update.message.text
            if not re.match(r"^09\d{9}$", phone):
                await update.message.reply_text("شماره تماس باید 11 رقم و با 09 شروع شود. دوباره وارد کنید:")
                return EDIT_PROFILE_VALUE
            c.execute("UPDATE users SET phone = ? WHERE user_id = ?", (phone, user_id))
        conn.commit()
        
    await update.message.reply_text("پروفایل شما با موفقیت ویرایش شد! ✅", reply_markup=get_main_menu())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو مکالمه فعلی"""
    user_info = get_user_info(update.effective_user.id)
    full_name = user_info[1] if user_info else "کاربر"
    await update.message.reply_text(
        f"{full_name} عزیز، عملیات لغو شد.",
        reply_markup=get_main_menu()
    )
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    """راه‌اندازی اصلی ربات"""
    init_db() # ایجاد پایگاه داده اگر وجود نداشته باشد
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler برای ثبت‌نام (profile_conv)
    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name)],
            CONFIRM_FULL_NAME: [CallbackQueryHandler(confirm_full_name)],
            NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, national_id)],
            CONFIRM_NATIONAL_ID: [CallbackQueryHandler(confirm_national_id)],
            STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_id)],
            CONFIRM_STUDENT_ID: [CallbackQueryHandler(confirm_student_id)],
            PHONE: [
                MessageHandler(filters.CONTACT, phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, phone)
            ],
            CONFIRM_PHONE: [CallbackQueryHandler(confirm_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        per_message=False
    )

    # ConversationHandler برای ویرایش پروفایل (edit_profile_conv)
    edit_profile_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(ویرایش مشخصات ✏️)$"), edit_profile_start)],
        states={
            EDIT_PROFILE: [CallbackQueryHandler(edit_profile)],
            EDIT_PROFILE_VALUE: [
                MessageHandler(filters.CONTACT, edit_profile_value),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_profile_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        per_message=False
    )

    # ثبت هندلرها
    app.add_handler(profile_conv)
    app.add_handler(edit_profile_conv)
    
    # هندلرهای سطح بالا
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(لغو/شروع دوباره 🚪)$"), reset_bot))

    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
