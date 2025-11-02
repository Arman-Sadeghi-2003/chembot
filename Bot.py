import os
import re
import sqlite3
import logging
from datetime import datetime, timedelta
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
import uuid

# تنظیم لاگر اصلی
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
# Bot configuration
BOT_TOKEN = "7996022698:AAG65GXEjbDbgMGFVT9ExeGFmkvj0UDqbXE"
CHANNEL_ID = "@chemical_eng_uma"
OPERATOR_GROUP_ID = -1002574996302
ADMIN_IDS = [5701423397, 158893761]
CARD_NUMBER = "6219-8619-2120-2437"
DB_PATH = "chemeng_bot.db"

def init_db():
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                type TEXT,
                date TEXT,
                location TEXT,
                capacity INTEGER,
                current_capacity INTEGER DEFAULT 0,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                hashtag TEXT,
                cost INTEGER,
                card_number TEXT,
                deactivation_reason TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_id INTEGER,
                registered_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_id INTEGER,
                amount INTEGER,
                confirmed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS operator_messages (
                message_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                user_id INTEGER,
                event_id INTEGER,
                message_type TEXT,
                sent_at TEXT
            )
        """)
        conn.commit()

# States for conversation handlers
FULL_NAME, CONFIRM_FULL_NAME, NATIONAL_ID, CONFIRM_NATIONAL_ID, STUDENT_ID, CONFIRM_STUDENT_ID, PHONE, CONFIRM_PHONE = range(8)
EDIT_PROFILE, EDIT_PROFILE_VALUE = range(2)
EVENT_TYPE, EVENT_TITLE, EVENT_DESCRIPTION, EVENT_COST, EVENT_DATE, EVENT_LOCATION, EVENT_CAPACITY, CONFIRM_EVENT = range(8)
EDIT_EVENT = 0
DEACTIVATE_REASON = 0
ANNOUNCE_GROUP, ANNOUNCE_MESSAGE = range(2)
ADD_ADMIN, REMOVE_ADMIN = range(2)
MANUAL_REG_EVENT, MANUAL_REG_STUDENT_ID, CONFIRM_MANUAL_REG = range(3)
REPORT_TYPE, REPORT_PERIOD = range(2)

# Utility functions
def validate_national_id(national_id: str) -> bool:
    if not re.match(r"^\d{10}$", national_id):
        return False
    check = int(national_id[9])
    total = sum(int(national_id[i]) * (10 - i) for i in range(9)) % 11
    return total < 2 and check == total or total >= 2 and check == 11 - total

def get_user_info(user_id: int) -> tuple:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return c.fetchone()

def get_admin_info(user_id: int) -> tuple:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        return c.fetchone()

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, update.effective_user.id)
        return member.status in ["member", "administrator", "creator"]
    except Forbidden:
        return False

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
        ["اضافه کردن رویداد جدید ➕", "تغییر رویداد فعال ✏️"],
        ["غیرفعال/فعال کردن رویداد 🔄", "مدیریت ادمین‌ها 👤"],
        ["اعلان عمومی 📢", "گزارش‌ها 📊"],
        ["اضافه کردن دستی به ثبت‌نام 📋"],
        ["لغو/شروع دوباره 🚪"],
        ["بازگشت 🔙"]
    ], resize_keyboard=True)

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
    user_info = get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("لطفاً نام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
        return FULL_NAME
    full_name = user_info[1]
    is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
    await update.message.reply_text(
        f"{full_name} عزیز، به ربات انجمن مهندسی شیمی خوش آمدید! 🎉",
        reply_markup=get_main_menu(is_admin)
    )
    return ConversationHandler.END

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if await check_channel_membership(update, context):
        user_id = update.effective_user.id
        user_info = get_user_info(user_id)
        if not user_info:
            await query.message.reply_text("لطفاً نام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
            await query.message.delete()
            return FULL_NAME
        full_name = user_info[1]
        is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
        await query.message.reply_text(
            f"{full_name} عزیز، به ربات انجمن مهندسی شیمی خوش آمدید! 🎉",
            reply_markup=get_main_menu(is_admin)
        )
        await query.message.delete()
        return ConversationHandler.END
    await query.message.reply_text(
        f"شما هنوز عضو کانال نیستید. لطفاً ابتدا کانال را دنبال کنید: {CHANNEL_ID} 📢",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
        ]])
    )
    return ConversationHandler.END

async def full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            one_time_keyboard=True
        )
    )
    await query.message.delete()
    return PHONE

async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    query = update.callback_query
    await query.answer()
    if query.data == "retry_phone":
        await query.message.reply_text(
            "لطفاً شماره تماس خود را دوباره وارد کنید یا دکمه زیر را فشار دهید:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
                one_time_keyboard=True
            )
        )
        await query.message.delete()
        return PHONE
    user_id = update.effective_user.id
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
    is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
    await query.message.reply_text(
        "پروفایل شما با موفقیت ایجاد شد! ✅",
        reply_markup=get_main_menu(is_admin)
    )
    await query.message.delete()
    return ConversationHandler.END

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    context.user_data.clear()  # پاک کردن تمام داده‌های موقت
    user_info = get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("لطفاً نام کامل خود را به فارسی وارد کنید (مثال: علی محمدی):")
        return FULL_NAME
    full_name = user_info[1]
    is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
    await update.message.reply_text(
        f"{full_name} عزیز، به ربات انجمن مهندسی شیمی خوش آمدید! 🎉",
        reply_markup=get_main_menu(is_admin)
    )

async def edit_profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if not await check_channel_membership(update, context):
        await update.message.reply_text(
            f"لطفاً ابتدا کانال رسمی را دنبال کنید: {CHANNEL_ID} 📢",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
            ]])
        )
        return ConversationHandler.END
    user_info = get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("ابتدا پروفایل خود را تکمیل کنید!", reply_markup=get_main_menu())
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
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if query.data == "cancel_edit":
        is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
        await query.message.reply_text("ویرایش لغو شد.", reply_markup=get_main_menu(is_admin))
        await query.message.delete()
        return ConversationHandler.END
    context.user_data["edit_field"] = query.data
    field_name = {
        "edit_full_name": "نام کامل",
        "edit_national_id": "کد ملی",
        "edit_student_id": "شماره دانشجویی",
        "edit_phone": "شماره تماس"
    }[query.data]
    if query.data == "edit_phone":
        await query.message.reply_text(
            f"لطفاً {field_name} جدید را وارد کنید یا دکمه زیر را فشار دهید:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
                one_time_keyboard=True
            )
        )
    else:
        await query.message.reply_text(f"لطفاً {field_name} جدید را وارد کنید:")
    await query.message.delete()
    return EDIT_PROFILE_VALUE

async def edit_profile_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    field = context.user_data["edit_field"]
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
    is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
    await update.message.reply_text("پروفایل شما با موفقیت ویرایش شد! ✅", reply_markup=get_main_menu(is_admin))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_info = get_user_info(update.effective_user.id)
    full_name = user_info[1] if user_info else "کاربر"
    is_admin = update.effective_user.id in ADMIN_IDS or bool(get_admin_info(update.effective_user.id))
    await update.message.reply_text(
        f"{full_name} عزیز، عملیات لغو شد.",
        reply_markup=get_main_menu(is_admin)
    )
    return ConversationHandler.END

async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_channel_membership(update, context):
        await update.message.reply_text(
            f"لطفاً ابتدا کانال رسمی را دنبال کنید: {CHANNEL_ID} 📢",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
            ]])
        )
        return
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id, title, type FROM events WHERE is_active = 1")
        events = c.fetchall()
    if not events:
        await update.message.reply_text("در حال حاضر دوره یا بازدید فعالی وجود ندارد. 📪")
        return
    buttons = [[InlineKeyboardButton(f"{event[1]} ({event[2]})", callback_data=f"event_{event[0]}")] for event in events]
    await update.message.reply_text(
        "رویدادهای فعال:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def event_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[1])
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
    if not event:
        await query.message.reply_text("رویداد یافت نشد!")
        return
    if not event[8]:  # is_active
        await query.message.reply_text(f"رویداد غیرفعال شده است. این رویداد: {event[12]}")
        return
    capacity_text = "نامحدود" if event[2] == "دوره" else f"{event[5] - event[6]}/{event[5]}"
    cost_text = "رایگان" if event[10] == 0 else f"{event[10]:,} تومان"
    text = (
        f"عنوان: {event[1]}\n"
        f"نوع: {event[2]}\n"
        f"تاریخ: {event[3]}\n"
        f"محل: {event[4]}\n"
        f"هزینه: {cost_text}\n"
        f"ظرفیت باقی‌مانده: {capacity_text}\n"
        f"توضیحات: {event[7]}"
    )
    buttons = [
        [InlineKeyboardButton("ثبت‌نام ✅", callback_data=f"register_{event_id}")],
        [InlineKeyboardButton("بازگشت 🔙", callback_data="back_to_events")]
    ]
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    await query.message.delete()

async def register_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await check_channel_membership(update, context):
        await query.message.reply_text(
            f"لطفاً ابتدا کانال رسمی را دنبال کنید: {CHANNEL_ID} 📢",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
            ]])
        )
        return
    event_id = int(query.data.split("_")[1])
    user_id = update.effective_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
        c.execute("SELECT * FROM registrations WHERE user_id = ? AND event_id = ?", (user_id, event_id))
        if c.fetchone():
            await query.message.reply_text("شما قبلاً ثبت‌نام کرده‌اید! 📋")
            return
        if not event[8]:
            await query.message.reply_text(f"رویداد غیرفعال شده است. دلیل: {event[12]}")
            return
        if event[2] != "دوره" and event[6] >= event[5]:
            await query.message.reply_text("ظرفیت تکمیل شده است. 📪 برای ثبت نام در لیست ذخیره، لطفاً با پشتیبانی تماس بگیرید.")
            return
    if event[10] == 0:  # Free event
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO registrations (user_id, event_id, registered_at) VALUES (?, ?, ?)",
                (user_id, event_id, datetime.now().isoformat())
            )
            c.execute(
                "UPDATE events SET current_capacity = current_capacity + 1 WHERE event_id = ?",
                (event_id,)
            )
            c.execute("SELECT full_name, national_id, student_id, phone FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()
            # محاسبه شماره ردیف
            c.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,))
            reg_count = c.fetchone()[0]
            conn.commit()
        hashtag = f"#{event[2]} #{event[9].replace(' ', '_')}"
        text = (
            f"{hashtag}\n"
            f"{reg_count}:\n"
            f"نام: {user[0]}\n"
            f"کد ملی: {user[1]}\n"
            f"شماره دانشجویی: {user[2]}\n"
            f"شماره تماس: {user[3]}"
        )
        message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message.message_id, OPERATOR_GROUP_ID, user_id, event_id, "registration", datetime.now().isoformat())
            )
            conn.commit()
        await query.message.reply_text("ثبت‌نام شما با موفقیت انجام شد! ✅ اپراتورها اطلاعات شما را دریافت کردند.")
        if event[2] != "دوره" and event[6] + 1 >= event[5]:
            await deactivate_event(event_id, "تکمیل ظرفیت", context)
    else:  # Paid event
        context.user_data["pending_event_id"] = event_id
        await query.message.reply_text(
            f"برای تکمیل ثبت‌نام در {event[1]}، لطفاً مبلغ {event[10]:,} تومان را به شماره کارت زیر واریز کنید:\n{CARD_NUMBER}\nلطفاً تصویر رسید پرداخت را ارسال کنید."
        )

async def handle_payment_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "pending_event_id" not in context.user_data:
        await update.message.reply_text("لطفاً ابتدا یک رویداد انتخاب کنید و فرآیند ثبت‌نام را آغاز کنید.")
        return
    event_id = context.user_data["pending_event_id"]
    user_id = update.effective_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
        c.execute("SELECT full_name, national_id, student_id, phone FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
    text = (
        f"#{event[2]} #{event[9].replace(' ', '_')}\n"
        f"نام: {user[0]}\n"
        f"کد ملی: {user[1]}\n"
        f"شماره دانشجویی: {user[2]}\n"
        f"شماره تماس: {user[3]}\n"
        f"مبلغ: {event[10]:,} تومان"
    )
    buttons = [
        [InlineKeyboardButton("تأیید ✅", callback_data=f"confirm_payment_{user_id}_{event_id}")],
        [
            InlineKeyboardButton("ناخوانا 📸", callback_data=f"unclear_payment_{user_id}_{event_id}"),
            InlineKeyboardButton("ابطال 🚫", callback_data=f"cancel_payment_{user_id}_{event_id}")
        ]
    ]
    message = await context.bot.send_photo(
        OPERATOR_GROUP_ID,
        update.message.photo[-1].file_id,
        caption=text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message.message_id, OPERATOR_GROUP_ID, user_id, event_id, "payment", datetime.now().isoformat())
        )
        conn.commit()
    await update.message.reply_text("رسید شما ارسال شد و در انتظار تأیید است. ✅")

# تابع مدیریت اقدامات پرداخت
async def payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS and not get_admin_info(update.effective_user.id):
        await query.answer("فقط ادمین‌ها می‌توانند این اقدام را انجام دهند! 🚫", show_alert=True)
        return

    callback_parts = query.data.split("_")
    if not callback_parts:
        logger.error(f"Empty callback data: {query.data}")
        await query.message.reply_text("خطایی رخ داد. داده دریافتی نامعتبر است.")
        await query.message.delete()
        return

    action = callback_parts[0]

    if action == "done":
        await query.message.delete()
        return

    # مدیریت دکمه‌های مرحله دوم (تأیید نهایی)
    if action == "confirm" and len(callback_parts) >= 5:
        sub_action = callback_parts[1]
        user_id = int(callback_parts[3])
        event_id = int(callback_parts[4])

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
            event = c.fetchone()
            c.execute("SELECT full_name, national_id, student_id, phone FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()

        if not event or not user:
            logger.error(f"Event or user not found: event_id={event_id}, user_id={user_id}")
            await query.message.reply_text("خطایی رخ داد. رویداد یا کاربر یافت نشد.")
            await query.message.delete()
            return

        if sub_action == "confirm_payment":
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO registrations (user_id, event_id, registered_at) VALUES (?, ?, ?)",
                    (user_id, event_id, datetime.now().isoformat())
                )
                c.execute(
                    "INSERT INTO payments (user_id, event_id, amount, confirmed_at) VALUES (?, ?, ?, ?)",
                    (user_id, event_id, event[10], datetime.now().isoformat())
                )
                c.execute(
                    "UPDATE events SET current_capacity = current_capacity + 1 WHERE event_id = ?",
                    (event_id,)
                )
                c.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,))
                reg_count = c.fetchone()[0]
                conn.commit()
            hashtag = f"#{event[2]} #{event[9].replace(' ', '_')}"
            text = (
                f"{hashtag}, {reg_count}:\n"
                f"نام: {user[0]}\n"
                f"کد ملی: {user[1]}\n"
                f"شماره دانشجویی: {user[2]}\n"
                f"شماره تماس: {user[3]}"
            )
            message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (message.message_id, OPERATOR_GROUP_ID, user_id, event_id, "registration", datetime.now().isoformat())
                )
                conn.commit()
            await context.bot.send_message(user_id, "پرداخت شما تأیید شد و ثبت‌نام شما تکمیل شد! ✅")
            if event[2] != "دوره" and event[6] + 1 >= event[5]:
                await deactivate_event(event_id, "تکمیل ظرفیت", context)
        elif sub_action == "unclear_payment":
            context.user_data["pending_event_id"] = event_id
            await context.bot.send_message(
                user_id,
                "رسید تراکنش شما ناخوانا یا غیرقابل بررسی بود. لطفاً رسید تراکنش‌تون رو دوباره آپلود کنید."
            )
        elif sub_action == "cancel_payment":
            if "pending_event_id" in context.user_data:
                del context.user_data["pending_event_id"]
            await context.bot.send_message(
                user_id,
                "پرداخت شما تأیید نشد. لطفاً فرآیند ثبت‌نام را دوباره انجام دهید."
            )
        await query.message.delete()
    # مدیریت دکمه‌های مرحله اول (تأیید، ناخوانا، ابطال)
    elif len(callback_parts) == 3 and action in ["confirm_payment", "unclear_payment", "cancel_payment"]:
        try:
            user_id = int(callback_parts[1])
            event_id = int(callback_parts[2])
            action_label = {
                "confirm_payment": "تأیید ✅",
                "unclear_payment": "ناخوانا 📸",
                "cancel_payment": "ابطال 🚫"
            }[action]
            buttons = [
                [InlineKeyboardButton(action_label, callback_data=f"confirm_{action}_{user_id}_{event_id}")],
                [InlineKeyboardButton("بازگشت", callback_data="done")]
            ]
            await query.message.edit_reply_markup(InlineKeyboardMarkup(buttons))
        except (KeyError, ValueError) as e:
            logger.error(f"Error processing callback data: {query.data}, error: {str(e)}")
            await query.message.reply_text("خطایی رخ داد. لطفاً دوباره تلاش کنید.")
            await query.message.delete()
    else:
        logger.error(f"Invalid callback data: {query.data}")
        await query.message.reply_text("خطایی رخ داد. فرمت داده نادرست است.")
        await query.message.delete()

async def deactivate_event(event_id: int, reason: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE events SET is_active = 0, deactivation_reason = ? WHERE event_id = ?",
            (reason, event_id)
        )
        c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
        c.execute("SELECT user_id FROM registrations WHERE event_id = ?", (event_id,))
        registrations = c.fetchall()
        conn.commit()
    users = []
    for reg in registrations:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT full_name, phone FROM users WHERE user_id = ?", (reg[0],))
            user = c.fetchone()
            users.append(f"- {user[0]} ({user[1]})")
    text = (
        f"#{event[2]} #{event[9].replace(' ', '_')}\n"
        f"#نهایی\n"
        f"تعداد ثبت‌نام‌کنندگان: {len(users)}\n"
        f"{' '.join(users)}"
    )
    message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message.message_id, OPERATOR_GROUP_ID, 0, event_id, "final_list", datetime.now().isoformat())
        )
        conn.commit()

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return
    await update.message.reply_text("منوی ادمین:", reply_markup=get_admin_menu())

async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    await update.message.reply_text(
        "نوع رویداد را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("دوره 📚", callback_data="دوره")],
            [InlineKeyboardButton("بازدید 🏭", callback_data="بازدید")]
        ])
    )
    return EVENT_TYPE

async def event_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["event_type"] = query.data
    await query.message.reply_text("لطفاً عنوان رویداد را وارد کنید (حداقل 3 کاراکتر):")
    await query.message.delete()
    return EVENT_TITLE

async def event_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text
    if len(title) < 3:
        await update.message.reply_text("عنوان باید حداقل 3 کاراکتر باشد. دوباره وارد کنید:")
        return EVENT_TITLE
    context.user_data["event_title"] = title
    hashtag = "#" + "_".join(title.split())
    context.user_data["event_hashtag"] = hashtag
    await update.message.reply_text("لطفاً توضیحات رویداد را وارد کنید (حداقل 10 کاراکتر، می‌توانید عکس هم ارسال کنید):")
    return EVENT_DESCRIPTION

async def event_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text or update.message.caption or ""
    if len(description) < 10:
        await update.message.reply_text("توضیحات باید حداقل 10 کاراکتر باشد. دوباره وارد کنید:")
        return EVENT_DESCRIPTION
    context.user_data["event_description"] = description
    if update.message.photo:
        context.user_data["event_photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("هزینه رویداد را وارد کنید (0 برای رایگان، یا مبلغ به تومان):")
    return EVENT_COST

async def event_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cost = update.message.text
    if not re.match(r"^\d+$", cost):
        await update.message.reply_text("هزینه باید عدد باشد. دوباره وارد کنید:")
        return EVENT_COST
    context.user_data["event_cost"] = int(cost)
    await update.message.reply_text("تاریخ رویداد را با فرمت YYYY-MM-DD وارد کنید:")
    return EVENT_DATE

async def event_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date = update.message.text
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        await update.message.reply_text("فرمت تاریخ باید YYYY-MM-DD باشد. دوباره وارد کنید:")
        return EVENT_DATE
    context.user_data["event_date"] = date
    await update.message.reply_text("محل رویداد را وارد کنید (حداقل 5 کاراکتر):")
    return EVENT_LOCATION

async def event_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.message.text
    if len(location) < 5:
        await update.message.reply_text("محل باید حداقل 5 کاراکتر باشد. دوباره وارد کنید:")
        return EVENT_LOCATION
    context.user_data["event_location"] = location
    if context.user_data["event_type"] == "دوره":
        context.user_data["event_capacity"] = 0
        return await confirm_event(update, context)
    await update.message.reply_text("ظرفیت رویداد را وارد کنید (عدد مثبت):")
    return EVENT_CAPACITY

async def event_capacity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    capacity = update.message.text
    if not re.match(r"^\d+$", capacity) or int(capacity) <= 0:
        await update.message.reply_text("ظرفیت باید عدد مثبت باشد. دوباره وارد کنید:")
        return EVENT_CAPACITY
    context.user_data["event_capacity"] = int(capacity)
    return await confirm_event(update, context)

async def confirm_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    event_data = context.user_data
    cost_text = "رایگان" if event_data["event_cost"] == 0 else f"{event_data['event_cost']:,} تومان"
    capacity_text = "نامحدود" if event_data["event_type"] == "دوره" else f"{event_data['event_capacity']}"
    text = (
        f"نوع: {event_data['event_type']}\n"
        f"عنوان: {event_data['event_title']}\n"
        f"هشتگ: {event_data['event_hashtag']}\n"
        f"توضیحات: {event_data['event_description']}\n"
        f"هزینه: {cost_text}\n"
        f"تاریخ: {event_data['event_date']}\n"
        f"محل: {event_data['event_location']}\n"
        f"ظرفیت: {capacity_text}"
    )
    if "event_photo" in event_data:
        await update.message.reply_photo(
            event_data["event_photo"],
            caption=text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("تأیید ✅", callback_data="confirm_event"),
                InlineKeyboardButton("لغو 🚫", callback_data="cancel_event")
            ]])
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("تأیید ✅", callback_data="confirm_event"),
                InlineKeyboardButton("لغو 🚫", callback_data="cancel_event")
            ]])
        )
    return CONFIRM_EVENT

async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_event":
        await query.message.reply_text("ایجاد رویداد لغو شد.", reply_markup=get_admin_menu())
        await query.message.delete()
        return ConversationHandler.END
    event_data = context.user_data
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO events (title, type, date, location, capacity, description, is_active, hashtag, cost, card_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_data["event_title"],
                    event_data["event_type"],
                    event_data["event_date"],
                    event_data["event_location"],
                    event_data.get("event_capacity", 0),
                    event_data["event_description"],
                    1,
                    event_data["event_hashtag"],
                    event_data["event_cost"],
                    CARD_NUMBER if event_data["event_cost"] > 0 else "",
                )
            )
            event_id = c.lastrowid
            conn.commit()
        logger.info(f"Event {event_id} created successfully")
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id, full_name FROM users")
            users = c.fetchall()
        for user in users:
            message = (
                f"{user[1]} عزیز،\n"
                f"یک #{event_data['event_type']} {event_data['event_hashtag']} اضافه شد.\n"
                f"می‌تونی جزئیات رو در کانال انجمن مهندسی شیمی بخونی و همین الان ثبت‌نام کنی..."
            )
            await context.bot.send_message(user[0], message)
            if "event_photo" in event_data:
                await context.bot.send_photo(
                    user[0],
                    event_data["event_photo"],
                    caption=event_data["event_description"]
                )
            else:
                await context.bot.send_message(user[0], f"توضیحات: {event_data['event_description']}")
            await context.bot.send_message(
                user[0],
                "ثبت‌نام کن 👇",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("ثبت‌نام ✅", callback_data=f"register_{event_id}")]
                ])
            )
        await query.message.reply_text("رویداد با موفقیت اضافه شد! ✅", reply_markup=get_admin_menu())
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error saving event: {str(e)}")
        await query.message.reply_text("خطایی در ذخیره رویداد رخ داد. لطفاً دوباره سعی کنید.")
        await query.message.delete()
    return ConversationHandler.END

async def edit_event_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id, title, type FROM events")
        events = c.fetchall()
    if not events:
        await update.message.reply_text("هیچ رویدادی وجود ندارد!", reply_markup=get_admin_menu())
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(f"{event[1]} ({event[2]})", callback_data=f"edit_event_{event[0]}")] for event in events]
    await update.message.reply_text("رویداد را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return EDIT_EVENT

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[2])
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
    context.user_data["edit_event_id"] = event_id
    cost_text = "رایگان" if event[10] == 0 else f"{event[10]:,} تومان"
    capacity_text = "نامحدود" if event[2] == "دوره" else f"{event[5]}"
    text = (
        f"نوع: {event[2]}\n"
        f"عنوان: {event[1]}\n"
        f"هشتگ: {event[9]}\n"
        f"توضیحات: {event[7]}\n"
        f"هزینه: {cost_text}\n"
        f"تاریخ: {event[3]}\n"
        f"محل: {event[4]}\n"
        f"ظرفیت: {capacity_text}"
    )
    await query.message.reply_text(
        "لطفاً متن ویرایش‌شده رویداد را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("لغو 🚫", callback_data="cancel_edit_event")
        ]])
    )
    await query.message.reply_text(text)
    await query.message.delete()
    return EDIT_EVENT

async def save_edited_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    event_id = context.user_data["edit_event_id"]
    try:
        lines = text.split("\n")
        event_data = {}
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                event_data[key.strip()] = value.strip()

        # بررسی وجود کلیدهای ضروری
        required_keys = ["نوع", "عنوان", "هشتگ", "توضیحات", "هزینه", "تاریخ", "محل", "ظرفیت"]
        missing_keys = [key for key in required_keys if key not in event_data]
        if missing_keys:
            await update.message.reply_text(
                f"خطا: فیلدهای زیر یافت نشدند: {', '.join(missing_keys)}\n"
                "لطفاً متن را با ساختار زیر وارد کنید:\n"
                "نوع: [دوره یا بازدید]\n"
                "عنوان: [عنوان]\n"
                "هشتگ: #[هشتگ]\n"
                "توضیحات: [توضیحات]\n"
                "هزینه: [هزینه یا رایگان]\n"
                "تاریخ: [YYYY-MM-DD]\n"
                "محل: [محل]\n"
                "ظرفیت: [ظرفیت یا نامحدود]"
            )
            return EDIT_EVENT

        # اعتبارسنجی مقادیر
        event_type = event_data["نوع"]
        if event_type not in ["دوره", "بازدید"]:
            raise ValueError("نوع رویداد باید 'دوره' یا 'بازدید' باشد.")

        title = event_data["عنوان"]
        if len(title) < 3:
            raise ValueError("عنوان باید حداقل 3 کاراکتر باشد.")

        hashtag = event_data["هشتگ"]
        if not hashtag.startswith("#"):
            raise ValueError("هشتگ باید با # شروع شود.")

        description = event_data["توضیحات"]
        if len(description) < 10:
            raise ValueError("توضیحات باید حداقل 10 کاراکتر باشد.")

        cost = event_data["هزینه"]
        cost = 0 if cost == "رایگان" else int(cost.replace(",", "").replace(" تومان", ""))

        date = event_data["تاریخ"]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise ValueError("فرمت تاریخ باید YYYY-MM-DD باشد.")

        location = event_data["محل"]
        if len(location) < 5:
            raise ValueError("محل باید حداقل 5 کاراکتر باشد.")

        capacity = event_data["ظرفیت"]
        capacity = 0 if capacity == "نامحدود" else int(capacity)
        if capacity < 0:
            raise ValueError("ظرفیت نمی‌تواند منفی باشد.")

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE events SET title = ?, type = ?, date = ?, location = ?, capacity = ?,
                description = ?, hashtag = ?, cost = ?, card_number = ?
                WHERE event_id = ?
                """,
                (
                    title, event_type, date, location, capacity, description, hashtag,
                    cost, CARD_NUMBER if cost > 0 else "", event_id
                )
            )
            conn.commit()
        await update.message.reply_text("رویداد با موفقیت ویرایش شد! ✅", reply_markup=get_admin_menu())
        return ConversationHandler.END
    except ValueError as e:
        logger.error(f"Error parsing edited event text: {str(e)}")
        await update.message.reply_text(f"خطا: {str(e)}\nلطفاً متن را با فرمت صحیح وارد کنید.")
        return EDIT_EVENT
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await update.message.reply_text("خطای غیرمنتظره رخ داد. لطفاً دوباره سعی کنید.")
        return EDIT_EVENT

async def toggle_event_status_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id, title, type, is_active FROM events")
        events = c.fetchall()
    if not events:
        await update.message.reply_text("هیچ رویدادی وجود ندارد!", reply_markup=get_admin_menu())
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(
        f"{event[1]} ({event[2]}) - {'فعال' if event[3] else 'غیرفعال'}",
        callback_data=f"toggle_event_{event[0]}"
    )] for event in events]
    await update.message.reply_text("رویداد را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return DEACTIVATE_REASON

async def toggle_event_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data.startswith("reason_"):
        reason = query.data.split("_")[1]
        event_id = context.user_data.get("toggle_event_id")
        if not event_id:
            await query.message.reply_text("خطا: رویداد انتخاب نشده است!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE events SET is_active = 0, deactivation_reason = ? WHERE event_id = ?",
                (reason, event_id)
            )
            conn.commit()
        await query.message.reply_text("رویداد با موفقیت غیرفعال شد! ✅", reply_markup=get_admin_menu())
        await query.message.delete()
        return ConversationHandler.END
    else:
        event_id = int(query.data.split("_")[2])
        context.user_data["toggle_event_id"] = event_id
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT is_active FROM events WHERE event_id = ?", (event_id,))
            is_active = c.fetchone()[0]
        if is_active:
            await query.message.reply_text(
                "علت غیرفعال کردن چیست؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("برگزار شد", callback_data="reason_برگزار شد")],
                    [InlineKeyboardButton("به تاخیر افتاد", callback_data="reason_به تاخیر افتاد")],
                    [InlineKeyboardButton("لغو شد", callback_data="reason_لغو شد")]
                ])
            )
        else:
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute(
                    "UPDATE events SET is_active = 1, deactivation_reason = '' WHERE event_id = ?",
                    (event_id,)
                )
                conn.commit()
            await query.message.reply_text("رویداد با موفقیت فعال شد! ✅", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        await query.message.delete()
        return DEACTIVATE_REASON

async def announce_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id, title, type FROM events")
        events = c.fetchall()
    buttons = [[InlineKeyboardButton(f"{event[1]} ({event[2]})", callback_data=f"announce_group_{event[0]}")] for event in events]
    buttons.append([InlineKeyboardButton("همه گروه‌ها", callback_data="announce_group_all")])
    await update.message.reply_text("گروه هدف اعلان را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return ANNOUNCE_GROUP

async def announce_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_data = query.data.split("_")[2]
    context.user_data["announce_group"] = group_data
    await query.message.reply_text("لطفاً متن اعلان را وارد کنید:")
    await query.message.delete()
    return ANNOUNCE_MESSAGE

async def send_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text
    group = context.user_data["announce_group"]
    if group == "all":
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM users")
            users = c.fetchall()
        for user in users:
            await context.bot.send_message(user[0], f"#اطلاعیه\n{message}")
    else:
        event_id = int(group)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT hashtag, type FROM events WHERE event_id = ?", (event_id,))
            event = c.fetchone()
            c.execute("SELECT user_id FROM registrations WHERE event_id = ?", (event_id,))
            users = c.fetchall()
        for user in users:
            await context.bot.send_message(user[0], f"#{event[1]} #{event[0].replace(' ', '_')}\n{message}")
    await update.message.reply_text("اعلان با موفقیت ارسال شد! ✅", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("فقط ادمین‌های اصلی می‌توانند ادمین‌ها را مدیریت کنند! 🚫")
        return ConversationHandler.END
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("اضافه کردن ادمین ➕", callback_data="add_admin")],
            [InlineKeyboardButton("حذف ادمین ➖", callback_data="remove_admin")]
        ])
    )
    return ADD_ADMIN

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "add_admin":
        await query.message.reply_text("لطفاً آیدی عددی ادمین جدید را وارد کنید:")
        await query.message.delete()
        return ADD_ADMIN
    elif query.data == "remove_admin":
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM admins")
            admins = c.fetchall()
        if not admins:
            await query.message.reply_text("هیچ ادمینی وجود ندارد!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(str(admin[0]), callback_data=f"remove_{admin[0]}")] for admin in admins]
        await query.message.reply_text("ادمین را برای حذف انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
        await query.message.delete()
        return REMOVE_ADMIN

async def save_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.text
    if not re.match(r"^\d+$", user_id):
        await update.message.reply_text("آیدی باید فقط شامل اعداد باشد. دوباره وارد کنید:")
        return ADD_ADMIN
    user_id = int(user_id)
    if user_id in ADMIN_IDS:
        await update.message.reply_text("این کاربر ادمین اصلی است و نمی‌توان آن را تغییر داد!", reply_markup=get_admin_menu())
        return ConversationHandler.END
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        if c.fetchone():
            await update.message.reply_text("این کاربر قبلاً ادمین است!", reply_markup=get_admin_menu())
            return ConversationHandler.END
        c.execute(
            "INSERT INTO admins (user_id, added_at) VALUES (?, ?)",
            (user_id, datetime.now().isoformat())
        )
        conn.commit()
    await update.message.reply_text("ادمین با موفقیت اضافه شد! ✅", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
    await query.message.reply_text("ادمین با موفقیت حذف شد! ✅", reply_markup=get_admin_menu())
    await query.message.delete()
    return ConversationHandler.END

async def manual_registration_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id, title, type FROM events WHERE is_active = 1")
        events = c.fetchall()
    if not events:
        await update.message.reply_text("هیچ رویداد فعالی وجود ندارد!", reply_markup=get_admin_menu())
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(f"{event[1]} ({event[2]})", callback_data=f"manual_reg_{event[0]}")] for event in events]
    await update.message.reply_text("رویداد را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return MANUAL_REG_EVENT

async def manual_registration_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[2])
    context.user_data["manual_reg_event_id"] = event_id
    await query.message.reply_text("لطفاً شماره دانشجویی کاربر را وارد کنید:")
    await query.message.delete()
    return MANUAL_REG_STUDENT_ID

async def manual_registration_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    student_id = update.message.text
    if not re.match(r"^\d+$", student_id):
        await update.message.reply_text("شماره دانشجویی باید فقط شامل اعداد باشد. دوباره وارد کنید:")
        return MANUAL_REG_STUDENT_ID
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE student_id = ?", (student_id,))
        user = c.fetchone()
    if not user:
        await update.message.reply_text("کاربری با این شماره دانشجویی یافت نشد. دوباره وارد کنید:")
        return MANUAL_REG_STUDENT_ID
    context.user_data["manual_reg_user_id"] = user[0]
    event_id = context.user_data["manual_reg_event_id"]
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT title, type FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
    text = (
        f"کاربر: {user[1]}\n"
        f"شماره دانشجویی: {user[3]}\n"
        f"رویداد: {event[0]} ({event[1]})"
    )
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("تأیید ✅", callback_data="confirm_manual_reg"),
            InlineKeyboardButton("لغو 🚫", callback_data="cancel_manual_reg")
        ]])
    )
    return CONFIRM_MANUAL_REG

async def confirm_manual_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_manual_reg":
        await query.message.reply_text("ثبت‌نام دستی لغو شد.", reply_markup=get_admin_menu())
        await query.message.delete()
        return ConversationHandler.END
    user_id = context.user_data["manual_reg_user_id"]
    event_id = context.user_data["manual_reg_event_id"]
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM registrations WHERE user_id = ? AND event_id = ?", (user_id, event_id))
        if c.fetchone():
            await query.message.reply_text("این کاربر قبلاً ثبت‌نام کرده است!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        c.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        event = c.fetchone()
        if event[2] != "دوره" and event[6] >= event[5]:
            await query.message.reply_text("ظرفیت رویداد تکمیل شده است!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        c.execute(
            "INSERT INTO registrations (user_id, event_id, registered_at) VALUES (?, ?, ?)",
            (user_id, event_id, datetime.now().isoformat())
        )
        c.execute(
            "UPDATE events SET current_capacity = current_capacity + 1 WHERE event_id = ?",
            (event_id,)
        )
        c.execute("SELECT full_name, national_id, student_id, phone FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        # محاسبه شماره ردیف
        c.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,))
        reg_count = c.fetchone()[0]
        conn.commit()
    text = (
        f"#{event[2]} #{event[9].replace(' ', '_')}, {reg_count}:\n"
        f"نام: {user[0]}\n"
        f"کد ملی: {user[1]}\n"
        f"شماره دانشجویی: {user[2]}\n"
        f"شماره تماس: {user[3]}"
    )
    message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message.message_id, OPERATOR_GROUP_ID, user_id, event_id, "registration", datetime.now().isoformat())
        )
        conn.commit()
    await query.message.reply_text("ثبت‌نام دستی با موفقیت انجام شد! ✅", reply_markup=get_admin_menu())
    await query.message.delete()
    if event[2] != "دوره" and event[6] + 1 >= event[5]:
        await deactivate_event(event_id, "تکمیل ظرفیت", context)
    return ConversationHandler.END

async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS and not get_admin_info(user_id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    await update.message.reply_text(
        "نوع گزارش را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("گزارش ثبت‌نام‌ها 📋", callback_data="report_registrations")],
            [InlineKeyboardButton("گزارش مالی 💸", callback_data="report_financial")]
        ])
    )
    return REPORT_TYPE

async def report_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["report_type"] = query.data
    if query.data == "report_registrations":
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT event_id, title, type, is_active FROM events")
            events = c.fetchall()
        if not events:
            await query.message.reply_text("هیچ رویدادی وجود ندارد!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(
            f"{event[1]} ({event[2]}) - {'فعال' if event[3] else 'غیرفعال'}",
            callback_data=f"report_event_{event[0]}"
        )] for event in events]
        await query.message.reply_text("رویداد را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
        await query.message.delete()
        return REPORT_PERIOD
    else:
        await query.message.reply_text(
            "بازه زمانی گزارش را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("امروز", callback_data="period_today")],
                [InlineKeyboardButton("هفته گذشته", callback_data="period_week")],
                [InlineKeyboardButton("ماه گذشته", callback_data="period_month")],
                [InlineKeyboardButton("همه", callback_data="period_all")]
            ])
        )
        await query.message.delete()
        return REPORT_PERIOD

async def generate_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    report_type = context.user_data["report_type"]
    if report_type == "report_registrations":
        event_id = int(query.data.split("_")[2])
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT title, type, hashtag FROM events WHERE event_id = ?", (event_id,))
            event = c.fetchone()
            c.execute(
                """
                SELECT u.full_name, u.national_id, u.student_id, u.phone
                FROM users u
                JOIN registrations r ON u.user_id = r.user_id
                WHERE r.event_id = ?
                ORDER BY r.registered_at
                """,
                (event_id,)
            )
            registrations = c.fetchall()
        if not registrations:
            await query.message.reply_text("هیچ ثبت‌نامی برای این رویداد وجود ندارد!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        text = f"#{event[1]} #{event[2].replace(' ', '_')}\n"
        for idx, reg in enumerate(registrations, 1):
            text += f"{idx}:{reg[0]}/{reg[1]}/{reg[2]}/{reg[3]}\n"
        await query.message.reply_text(text, reply_markup=get_admin_menu())
        await query.message.delete()
        return ConversationHandler.END
    else:  # report_financial
        period = query.data.split("_")[1]
        now = datetime.now()
        if period == "today":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        elif period == "week":
            start_date = (now - timedelta(days=7)).isoformat()
        elif period == "month":
            start_date = (now - timedelta(days=30)).isoformat()
        else:
            start_date = "1970-01-01T00:00:00"
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT e.title, e.type, u.full_name, u.national_id, p.amount
                FROM events e
                LEFT JOIN payments p ON e.event_id = p.event_id
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE p.confirmed_at >= ? OR p.confirmed_at IS NULL
                """,
                (start_date,)
            )
            reports = c.fetchall()
        if not reports:
            await query.message.reply_text("هیچ پرداختی در این بازه زمانی ثبت نشده است!", reply_markup=get_admin_menu())
            await query.message.delete()
            return ConversationHandler.END
        text = "گزارش مالی:\n"
        for report in reports:
            if report[4]:  # اگر پرداختی وجود داشته باشد
                text += (
                    f"رویداد: {report[0]} ({report[1]})\n"
                    f"نام: {report[2]}\n"
                    f"کد ملی: {report[3]}\n"
                    f"مبلغ: {report[4]:,} تومان\n"
                    "-------------------\n"
                )
        await query.message.reply_text(text, reply_markup=get_admin_menu())
        await query.message.delete()
        return ConversationHandler.END

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_info = get_user_info(user.id)
    identifier = f"@{user.username}" if user.username else f"شماره: {user_info[4] if user_info else 'نامشخص'}"
    text = f"📞 درخواست پشتیبانی از {identifier}:\n{update.message.text}"
    message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message.message_id, OPERATOR_GROUP_ID, user.id, 0, "support", datetime.now().isoformat())
        )
        conn.commit()
    await update.message.reply_text(
        "پیام شما به تیم پشتیبانی ارسال شد. 📬 در اسرع وقت پاسخ خواهیم داد.",
        reply_markup=get_main_menu(user.id in ADMIN_IDS or bool(get_admin_info(user.id)))
    )

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "❓ **سوالات متداول**\n\n"
        "1️⃣ **چطور می‌توانم در رویدادها ثبت‌نام کنم؟**\n"
        "از منوی اصلی، گزینه 'دوره‌ها/بازدیدها 📅' را انتخاب کنید، رویداد مورد نظر را انتخاب کرده و دکمه ثبت‌نام را بزنید.\n\n"
        "2️⃣ **هزینه ثبت‌نام چطور پرداخت می‌شود؟**\n"
        "برای رویدادهای غیررایگان، شماره کارت نمایش داده می‌شود. پس از واریز مبلغ، تصویر رسید را ارسال کنید.\n\n"
        "3️⃣ **چطور می‌توانم پروفایلم را ویرایش کنم؟**\n"
        "از منوی اصلی، گزینه 'ویرایش مشخصات ✏️' را انتخاب کنید و اطلاعات مورد نظر را تغییر دهید.\n\n"
        "4️⃣ **اگر مشکلی داشتم با کجا تماس بگیرم؟**\n"
        "از گزینه 'ارتباط با پشتیبانی 📞' در منوی اصلی استفاده کنید تا پیام شما به تیم پشتیبانی ارسال شود.\n\n"
        "5️⃣ **چطور می‌توانم از وضعیت ثبت‌نامم مطمئن شوم؟**\n"
        "پس از ثبت‌نام، تأییدیه‌ای دریافت خواهید کرد. برای جزئیات بیشتر با پشتیبانی تماس بگیرید."
    )
    await update.message.reply_text(text, reply_markup=get_main_menu(update.effective_user.id in ADMIN_IDS or bool(get_admin_info(update.effective_user.id))))

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    full_name = user_info[1] if user_info else "کاربر"
    is_admin = user_id in ADMIN_IDS or bool(get_admin_info(user_id))
    await update.message.reply_text(
        f"{full_name} عزیز، به منوی اصلی بازگشتید.",
        reply_markup=get_main_menu(is_admin)
    )

def main() -> None:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler برای profile_conv
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
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای edit_profile_conv
    edit_profile_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(ویرایش مشخصات ✏️)$"), edit_profile_start)],
        states={
            EDIT_PROFILE: [CallbackQueryHandler(edit_profile)],
            EDIT_PROFILE_VALUE: [
                MessageHandler(filters.CONTACT, edit_profile_value),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_profile_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای add_event_conv
    add_event_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(اضافه کردن رویداد جدید ➕)$"), add_event)],
        states={
            EVENT_TYPE: [CallbackQueryHandler(event_type)],
            EVENT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_title)],
            EVENT_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, event_description),
                MessageHandler(filters.PHOTO, event_description),
            ],
            EVENT_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_cost)],
            EVENT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_date)],
            EVENT_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_location)],
            EVENT_CAPACITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_capacity)],
            CONFIRM_EVENT: [CallbackQueryHandler(save_event)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای edit_event_conv
    edit_event_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(تغییر رویداد فعال ✏️)$"), edit_event_start)],
        states={
            EDIT_EVENT: [
                CallbackQueryHandler(edit_event),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_event),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای toggle_event_conv
    toggle_event_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(غیرفعال/فعال کردن رویداد 🔄)$"), toggle_event_status_start)],
        states={
            DEACTIVATE_REASON: [CallbackQueryHandler(toggle_event_status)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای announce_conv
    announce_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(اعلان عمومی 📢)$"), announce_start)],
        states={
            ANNOUNCE_GROUP: [CallbackQueryHandler(announce_group)],
            ANNOUNCE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_announcement)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای manage_admins_conv
    manage_admins_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(مدیریت ادمین‌ها 👤)$"), manage_admins)],
        states={
            ADD_ADMIN: [
                CallbackQueryHandler(add_admin),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_admin),
            ],
            REMOVE_ADMIN: [CallbackQueryHandler(remove_admin)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای manual_reg_conv
    manual_reg_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(اضافه کردن دستی به ثبت‌نام 📋)$"), manual_registration_start)],
        states={
            MANUAL_REG_EVENT: [CallbackQueryHandler(manual_registration_event)],
            MANUAL_REG_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_registration_student_id)],
            CONFIRM_MANUAL_REG: [CallbackQueryHandler(confirm_manual_registration)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ConversationHandler برای report_conv
    report_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(گزارش‌ها 📊)$"), report_start)],
        states={
            REPORT_TYPE: [CallbackQueryHandler(report_type)],
            REPORT_PERIOD: [CallbackQueryHandler(generate_report)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # ثبت هندلرها
    app.add_handler(profile_conv)
    app.add_handler(edit_profile_conv)
    app.add_handler(add_event_conv)
    app.add_handler(edit_event_conv)
    app.add_handler(toggle_event_conv)
    app.add_handler(announce_conv)
    app.add_handler(manage_admins_conv)
    app.add_handler(manual_reg_conv)
    app.add_handler(report_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(دوره‌ها/بازدیدها 📅)$"), show_events))
    app.add_handler(MessageHandler(filters.Regex("^(ارتباط با پشتیبانی 📞)$"), handle_support_message))
    app.add_handler(MessageHandler(filters.Regex("^(سوالات متداول ❓)$"), faq))
    app.add_handler(MessageHandler(filters.Regex("^(لغو/شروع دوباره 🚪)$"), reset_bot))
    app.add_handler(MessageHandler(filters.Regex("^(منوی ادمین ⚙️)$"), admin_menu))
    app.add_handler(MessageHandler(filters.Regex("^(بازگشت 🔙)$"), back_to_main))
    app.add_handler(CallbackQueryHandler(event_details, pattern="^event_"))
    app.add_handler(CallbackQueryHandler(register_event, pattern="^register_"))
    app.add_handler(CallbackQueryHandler(payment_action, pattern="^(confirm_payment_|unclear_payment_|cancel_payment_|confirm_|done)"))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_payment_receipt))
    app.add_handler(CallbackQueryHandler(check_membership, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(show_events, pattern="^back_to_events$"))

    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
