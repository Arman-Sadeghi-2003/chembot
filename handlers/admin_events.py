# handlers/admin_events.py
import re
import logging
from enum import Enum, auto
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

import database as db
from config import CARD_NUMBER
from handlers.common import get_admin_menu, cancel, is_user_admin

logger = logging.getLogger(__name__)

# --- States ---
class EventState(Enum):
    TYPE = auto()
    TITLE = auto()
    DESCRIPTION = auto()
    COST = auto()
    DATE = auto()
    LOCATION = auto()
    CAPACITY = auto()
    CONFIRM = auto()

class EditEventState(Enum):
    CHOOSE_EVENT = auto()
    CHOOSE_FIELD = auto()
    GET_NEW_VALUE = auto()

class ToggleEventState(Enum):
    CHOOSE_EVENT = auto()
    GET_REASON = auto()

# --- 1. Add Event Conversation ---

async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_user_admin(update.effective_user.id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
    await update.message.reply_text(
        "نوع رویداد را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("دوره 📚", callback_data="دوره")],
            [InlineKeyboardButton("بازدید 🏭", callback_data="بازدید")]
        ])
    )
    return EventState.TYPE

async def event_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["event_type"] = query.data
    await query.message.edit_text("لطفاً عنوان رویداد را وارد کنید (حداقل 3 کاراکتر):")
    return EventState.TITLE

async def event_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text
    if len(title) < 3:
        await update.message.reply_text("عنوان باید حداقل 3 کاراکتر باشد. دوباره وارد کنید:")
        return EventState.TITLE
    context.user_data["event_title"] = title
    hashtag = "#" + "_".join(title.split())
    context.user_data["event_hashtag"] = hashtag
    await update.message.reply_text("لطفاً توضیحات رویداد را وارد کنید (حداقل 10 کاراکتر):")
    return EventState.DESCRIPTION

async def event_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text or update.message.caption or ""
    if len(description) < 10:
        await update.message.reply_text("توضیحات باید حداقل 10 کاراکتر باشد. دوباره وارد کنید:")
        return EventState.DESCRIPTION
    context.user_data["event_description"] = description
    if update.message.photo:
        context.user_data["event_photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("هزینه رویداد را وارد کنید (0 برای رایگان، یا مبلغ به تومان):")
    return EventState.COST

async def event_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cost = update.message.text
    if not re.match(r"^\d+$", cost):
        await update.message.reply_text("هزینه باید عدد باشد. دوباره وارد کنید:")
        return EventState.COST
    context.user_data["event_cost"] = int(cost)
    await update.message.reply_text("تاریخ رویداد را با فرمت YYYY-MM-DD وارد کنید:")
    return EventState.DATE

async def event_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date = update.message.text
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("فرمت تاریخ باید YYYY-MM-DD باشد. دوباره وارد کنید:")
        return EventState.DATE
    context.user_data["event_date"] = date
    await update.message.reply_text("محل رویداد را وارد کنید (حداقل 5 کاراکتر):")
    return EventState.LOCATION

async def event_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.message.text
    if len(location) < 5:
        await update.message.reply_text("محل باید حداقل 5 کاراکتر باشد. دوباره وارد کنید:")
        return EventState.LOCATION
    context.user_data["event_location"] = location
    if context.user_data["event_type"] == "دوره":
        context.user_data["event_capacity"] = 0
        return await confirm_event(update, context)  # Skip capacity step
    await update.message.reply_text("ظرفیت رویداد را وارد کنید (عدد مثبت):")
    return EventState.CAPACITY

async def event_capacity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    capacity = update.message.text
    if not re.match(r"^\d+$", capacity) or int(capacity) <= 0:
        await update.message.reply_text("ظرفیت باید عدد مثبت باشد. دوباره وارد کنید:")
        return EventState.CAPACITY
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
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("تأیید ✅", callback_data="confirm_event"),
        InlineKeyboardButton("لغو 🚫", callback_data="cancel_event")
    ]])
    
    if "event_photo" in event_data:
        await update.message.reply_photo(
            event_data["event_photo"], caption=text, reply_markup=markup
        )
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return EventState.CONFIRM

async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_event":
        await query.message.edit_text("ایجاد رویداد لغو شد.", reply_markup=get_admin_menu())
        return ConversationHandler.END
        
    event_data = context.user_data
    try:
        async with await db.get_db_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO events (title, type, date, location, capacity, description, is_active, hashtag, cost, card_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_data["event_title"], event_data["event_type"],
                    event_data["event_date"], event_data["event_location"],
                    event_data.get("event_capacity", 0), event_data["event_description"],
                    1, event_data["event_hashtag"], event_data["event_cost"],
                    CARD_NUMBER if event_data["event_cost"] > 0 else "",
                )
            )
            event_id = cursor.lastrowid
            await conn.commit()
            
            logger.info(f"Event {event_id} created successfully")
            
            async with conn.execute("SELECT user_id, full_name FROM users") as cursor:
                users = await cursor.fetchall()
        
        # Broadcast to users (add rate limiting)
        # ... (broadcast logic remains same) ...

        await query.message.edit_text("رویداد با موفقیت اضافه شد! ✅", reply_markup=get_admin_menu())
        
    except Exception as e:
        logger.error(f"Error saving event: {str(e)}")
        await query.message.edit_text("خطایی در ذخیره رویداد رخ داد. لطفاً دوباره سعی کنید.")
        
    return ConversationHandler.END

add_event_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(اضافه کردن رویداد جدید ➕)$"), add_event)],
    states={
        EventState.TYPE: [CallbackQueryHandler(event_type, pattern="^(دوره|بازدید)$")],
        EventState.TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_title)],
        EventState.DESCRIPTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, event_description),
            MessageHandler(filters.PHOTO, event_description),
        ],
        EventState.COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_cost)],
        EventState.DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_date)],
        EventState.LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_location)],
        EventState.CAPACITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_capacity)],
        EventState.CONFIRM: [CallbackQueryHandler(save_event, pattern="^(confirm_event|cancel_event)$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)


# --- 2. Edit Event Conversation (Improved) ---

async def edit_event_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_user_admin(update.effective_user.id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
        
    events = await db.get_all_events()
            
    if not events:
        await update.message.reply_text("هیچ رویدادی وجود ندارد!", reply_markup=get_admin_menu())
        return ConversationHandler.END
        
    buttons = [[InlineKeyboardButton(
        f"{event['title']} ({event['type']}) - {event['date']}", 
        callback_data=f"edit_event_{event['event_id']}"
    )] for event in events]
    
    await update.message.reply_text("کدام رویداد را می‌خواهید ویرایش کنید؟", reply_markup=InlineKeyboardMarkup(buttons))
    return EditEventState.CHOOSE_EVENT

async def edit_event_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    event_id = int(query.data.split("_")[2])
    context.user_data["edit_event_id"] = event_id
    
    event = await db.get_event_details(event_id)
    if not event:
        await query.message.edit_text("رویداد یافت نشد.", reply_markup=get_admin_menu())
        return ConversationHandler.END

    cost_text = "رایگان" if event['cost'] == 0 else f"{event['cost']:,} تومان"
    capacity_text = "نامحدود" if event['type'] == "دوره" else f"{event['capacity']}"

    text = (
        f"رویداد: {event['title']}\n"
        f"تاریخ: {event['date']} | هزینه: {cost_text} | ظرفیت: {capacity_text}\n"
        f"کدام بخش را می‌خواهید ویرایش کنید؟"
    )
    
    buttons = [
        [
            InlineKeyboardButton("عنوان", callback_data="edit_field_title"),
            InlineKeyboardButton("تاریخ", callback_data="edit_field_date"),
        ],
        [
            InlineKeyboardButton("هزینه", callback_data="edit_field_cost"),
            InlineKeyboardButton("ظرفیت", callback_data="edit_field_capacity"),
        ],
        [
            InlineKeyboardButton("مکان", callback_data="edit_field_location"),
            InlineKeyboardButton("توضیحات", callback_data="edit_field_description"),
        ],
        [InlineKeyboardButton("لغو 🚫", callback_data="cancel_edit")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return EditEventState.CHOOSE_FIELD


async def edit_event_get_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_edit":
        await query.message.edit_text("عملیات لغو شد.", reply_markup=get_admin_menu())
        context.user_data.clear()
        return ConversationHandler.END

    field = query.data.split("_")[2] # e.g., "title"
    context.user_data["edit_field"] = field
    
    field_map_fa = {
        "title": "عنوان", "description": "توضیحات", "cost": "هزینه (عدد، 0 برای رایگان)",
        "date": "تاریخ (YYYY-MM-DD)", "location": "مکان", "capacity": "ظرفیت (عدد)"
    }
    
    await query.message.edit_text(f"لطفاً {field_map_fa.get(field, 'مقدار')} جدید را وارد کنید:")
    return EditEventState.GET_NEW_VALUE

async def edit_event_save_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_value = update.message.text
        field = context.user_data.get("edit_field")
        event_id = context.user_data.get("edit_event_id")

        if not field or not event_id:
            await update.message.reply_text("خطا: اطلاعات ویرایش یافت نشد. لطفاً لغو کنید و دوباره شروع کنید.", reply_markup=get_admin_menu())
            return ConversationHandler.END

        # --- اعتبارسنجی ---
        validated_value = new_value
        if field == "cost" or field == "capacity":
            if not re.match(r"^\d+$", new_value):
                await update.message.reply_text("مقدار باید عددی باشد. دوباره وارد کنید:")
                return EditEventState.GET_NEW_VALUE
            validated_value = int(new_value)
        
        elif field == "date":
            try:
                datetime.strptime(new_value, "%Y-%m-%d")
            except ValueError:
                await update.message.reply_text("فرمت تاریخ باید YYYY-MM-DD باشد. دوباره وارد کنید:")
                return EditEventState.GET_NEW_VALUE
        
        elif field == "title" and len(new_value) < 3:
             await update.message.reply_text("عنوان باید حداقل 3 کاراکتر باشد. دوباره وارد کنید:")
             return EditEventState.GET_NEW_VALUE

        # --- ذخیره در دیتابیس ---
        success = await db.update_event_field(event_id, field, validated_value)
        if success:
            await update.message.reply_text(f"فیلد '{field}' با موفقیت به‌روز شد. ✅", reply_markup=get_admin_menu())
            context.user_data.clear()
            return ConversationHandler.END
        else:
            await update.message.reply_text("خطایی در ذخیره اطلاعات رخ داد.", reply_markup=get_admin_menu())
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in edit_event_save_value: {e}")
        await update.message.reply_text("خطای غیرمنتظره. لطفاً لغو کنید.", reply_markup=get_admin_menu())
        return ConversationHandler.END

edit_event_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(ویرایش رویدادها ✏️)$"), edit_event_start)],
    states={
        EditEventState.CHOOSE_EVENT: [CallbackQueryHandler(edit_event_choose_field, pattern="^edit_event_")],
        EditEventState.CHOOSE_FIELD: [CallbackQueryHandler(edit_event_get_value, pattern="^(edit_field_|cancel_edit)"), ],
        EditEventState.GET_NEW_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_event_save_value)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)


# --- 3. Toggle Event Status Conversation ---

async def toggle_event_status_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_user_admin(update.effective_user.id):
        await update.message.reply_text("شما دسترسی ادمین ندارید! 🚫")
        return ConversationHandler.END
        
    events = await db.get_all_events()
    if not events:
        await update.message.reply_text("هیچ رویدادی وجود ندارد!", reply_markup=get_admin_menu())
        return ConversationHandler.END
        
    buttons = [[InlineKeyboardButton(
        f"{event['title']} ({'فعال' if event['is_active'] else 'غیرفعال'})",
        callback_data=f"toggle_event_{event['event_id']}"
    )] for event in events]
    
    await update.message.reply_text("رویداد را برای تغییر وضعیت انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return ToggleEventState.CHOOSE_EVENT

async def toggle_event_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    event_id = int(query.data.split("_")[2])
    context.user_data["toggle_event_id"] = event_id
    
    try:
        event = await db.get_event_details(event_id)
        if not event:
            await query.message.edit_text("رویداد یافت نشد!", reply_markup=get_admin_menu())
            return ConversationHandler.END
        
        if event['is_active']:
            # Event is active, ask for deactivation reason
            await query.message.edit_text(
                "علت غیرفعال کردن چیست؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("برگزار شد", callback_data="reason_برگزار شد")],
                    [InlineKeyboardButton("به تاخیر افتاد", callback_data="reason_به تاخیر افتاد")],
                    [InlineKeyboardButton("لغو شد", callback_data="reason_لغو شد")]
                ])
            )
            return ToggleEventState.GET_REASON
        else:
            # Event is inactive, activate it
            async with await db.get_db_connection() as conn:
                await conn.execute(
                    "UPDATE events SET is_active = 1, deactivation_reason = '' WHERE event_id = ?",
                    (event_id,)
                )
                await conn.commit()
            await query.message.edit_text("رویداد با موفقیت فعال شد! ✅", reply_markup=get_admin_menu())
            return ConversationHandler.END
                
    except Exception as e:
        logger.error(f"Error toggling event {event_id}: {e}")
        await query.message.edit_text("خطایی در پایگاه داده رخ داد.")
        return ConversationHandler.END

async def toggle_event_status_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    reason = query.data.split("reason_")[1]
    event_id = context.user_data.get("toggle_event_id")
    
    if not event_id:
        await query.message.edit_text("خطا: رویداد انتخاب نشده است!", reply_markup=get_admin_menu())
        return ConversationHandler.END
        
    try:
        async with await db.get_db_connection() as conn:
            await conn.execute(
                "UPDATE events SET is_active = 0, deactivation_reason = ? WHERE event_id = ?",
                (reason, event_id)
            )
            await conn.commit()
            
        await query.message.edit_text("رویداد با موفقیت غیرفعال شد! ✅", reply_markup=get_admin_menu())
        
    except Exception as e:
        logger.error(f"Error deactivating event {event_id} with reason: {e}")
        await query.message.edit_text("خطایی در پایگاه داده رخ داد.")
        
    return ConversationHandler.END

toggle_event_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(غیرفعال/فعال کردن رویداد 🔄)$"), toggle_event_status_start)],
    states={
        ToggleEventState.CHOOSE_EVENT: [CallbackQueryHandler(toggle_event_status, pattern="^toggle_event_")],
        ToggleEventState.GET_REASON: [CallbackQueryHandler(toggle_event_status_reason, pattern="^reason_")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)
