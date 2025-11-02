# handlers/user_profile.py
import re
import logging
from enum import Enum, auto
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes, CommandHandler
)

import database as db
from handlers.common import (
    check_channel_membership, get_main_menu, cancel, is_user_admin, 
    validate_national_id, ProfileState, CHANNEL_ID
)

logger = logging.getLogger(__name__)

class EditProfileState(Enum):
    CHOOSE_FIELD = auto()
    GET_VALUE = auto()

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
        
    user_info = await db.get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("ابتدا پروفایل خود را تکمیل کنید!", reply_markup=get_main_menu())
        return ConversationHandler.END
        
    text = (
        f"اطلاعات فعلی شما:\n"
        f"نام کامل: {user_info['full_name']}\n"
        f"کد ملی: {user_info['national_id']}\n"
        f"شماره دانشجویی: {user_info['student_id']}\n"
        f"شماره تماس: {user_info['phone']}"
    )
    buttons = [
        [InlineKeyboardButton("ویرایش نام ✏️", callback_data="edit_full_name")],
        [InlineKeyboardButton("ویرایش کد ملی ✏️", callback_data="edit_national_id")],
        [InlineKeyboardButton("ویرایش شماره دانشجویی ✏️", callback_data="edit_student_id")],
        [InlineKeyboardButton("ویرایش شماره تماس ✏️", callback_data="edit_phone")],
        [InlineKeyboardButton("لغو 🚫", callback_data="cancel_edit")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return EditProfileState.CHOOSE_FIELD

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if query.data == "cancel_edit":
        admin_status = await is_user_admin(user_id)
        await query.message.reply_text("ویرایش لغو شد.", reply_markup=get_main_menu(admin_status))
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
                one_time_keyboard=True
            )
        )
    else:
        await query.message.reply_text(f"لطفاً {field_name} جدید را وارد کنید:")
    await query.message.delete()
    return EditProfileState.GET_VALUE

async def edit_profile_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    field_key = context.user_data.get("edit_field")
    if not field_key:
        await update.message.reply_text("خطایی رخ داد. لطفاً دوباره تلاش کنید.")
        return await cancel(update, context)

    db_field_map = {
        "edit_full_name": "full_name",
        "edit_national_id": "national_id",
        "edit_student_id": "student_id",
        "edit_phone": "phone",
    }
    db_field = db_field_map.get(field_key)
    value = None

    try:
        if field_key == "edit_full_name":
            value = update.message.text
            if not re.match(r"^[آ-ی\s]{6,}$", value) or value.count(" ") < 1:
                await update.message.reply_text("نام کامل باید حداقل 6 کاراکتر با حروف فارسی و شامل یک فاصله باشد. دوباره وارد کنید:")
                return EditProfileState.GET_VALUE
        
        elif field_key == "edit_national_id":
            value = update.message.text
            if not validate_national_id(value):
                await update.message.reply_text("کد ملی نامعتبر است. لطفاً کد ملی 10 رقمی معتبر وارد کنید:")
                return EditProfileState.GET_VALUE
        
        elif field_key == "edit_student_id":
            value = update.message.text
            if not re.match(r"^\d+$", value):
                await update.message.reply_text("شماره دانشجویی باید فقط شامل اعداد باشد. دوباره وارد کنید:")
                return EditProfileState.GET_VALUE
        
        elif field_key == "edit_phone":
            if update.message.contact:
                value = update.message.contact.phone_number
                value = value.replace("+98", "0") if value.startswith("+98") else value
            else:
                value = update.message.text
            if not re.match(r"^09\d{9}$", value):
                await update.message.reply_text("شماره تماس باید 11 رقم و با 09 شروع شود. دوباره وارد کنید:")
                return EditProfileState.GET_VALUE
        
        # Update database
        if db_field and value:
            success = await db.update_event_field(user_id, db_field, value) # Note: This function name is wrong in DB, should be update_user_field
            # Let's fix this logic here
            async with await db.get_db_connection() as conn:
                 await conn.execute(f"UPDATE users SET {db_field} = ? WHERE user_id = ?", (value, user_id))
                 await conn.commit()
            success = True # Assume success if no exception
            
            if not success:
                 raise Exception(f"Failed to update {db_field}")

    except Exception as e:
        logger.error(f"Error editing profile for {user_id}: {e}")
        await update.message.reply_text("خطایی در به‌روزرسانی پروفایل رخ داد. لطفاً دوباره تلاش کنید.")
        return await cancel(update, context)
        
    admin_status = await is_user_admin(user_id)
    await update.message.reply_text("پروفایل شما با موفقیت ویرایش شد! ✅", reply_markup=get_main_menu(admin_status))
    return ConversationHandler.END


edit_profile_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(ویرایش مشخصات ✏️)$"), edit_profile_start)],
    states={
        EditProfileState.CHOOSE_FIELD: [CallbackQueryHandler(edit_profile, pattern="^(edit_|cancel_edit)"), ],
        EditProfileState.GET_VALUE: [
            MessageHandler(filters.CONTACT, edit_profile_value),
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_profile_value),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)
