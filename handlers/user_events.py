# handlers/user_events.py
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
from config import CHANNEL_ID, CARD_NUMBER, OPERATOR_GROUP_ID
from handlers.common import check_channel_membership, is_user_admin

logger = logging.getLogger(__name__)

async def deactivate_event(event_id: int, reason: str, context: ContextTypes.DEFAULT_TYPE):
    """
    رویداد را غیرفعال می‌کند و لیست نهایی ثبت‌نام‌کنندگان را به گروه اپراتورها ارسال می‌کند.
    """
    try:
        async with await db.get_db_connection() as conn:
            # 1. غیرفعال کردن رویداد
            await conn.execute(
                "UPDATE events SET is_active = 0, deactivation_reason = ? WHERE event_id = ?",
                (reason, event_id)
            )
            event = await db.get_event_details(event_id)
            registrations = await db.get_event_participants(event_id)
            await conn.commit()
            
            # 2. آماده‌سازی و ارسال لیست نهایی
            users = []
            for reg in registrations:
                user = await db.get_user_info(reg['user_id'])
                if user:
                    users.append(f"- {user['full_name']} ({user['phone']})")

            text = (
                f"#{event['type']} #{event['hashtag'].replace(' ', '_')}\n"
                f"#نهایی\n"
                f"تعداد ثبت‌نام‌کنندگان: {len(users)}\n"
                f"{' '.join(users)}"
            )
            message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
            
            # 3. ثبت پیام در دیتابیس
            await conn.execute(
                "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message.message_id, OPERATOR_GROUP_ID, 0, event_id, "final_list", datetime.now().isoformat())
            )
            await conn.commit()
            logger.info(f"Event {event_id} deactivated. Reason: {reason}")
            
    except Exception as e:
        logger.error(f"Error deactivating event {event_id}: {e}")


async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رویدادهای فعال را نمایش می‌دهد."""
    user_id = update.effective_user.id
    message = update.message or update.callback_query.message

    if not await check_channel_membership(update, context):
        await message.reply_text(
            f"لطفاً ابتدا کانال رسمی را دنبال کنید: {CHANNEL_ID} 📢",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("عضو شدم ✅", callback_data="check_membership")
            ]])
        )
        return
        
    async with await db.get_db_connection() as conn:
        async with conn.execute("SELECT event_id, title, type FROM events WHERE is_active = 1") as cursor:
            events = await cursor.fetchall()
            
    if not events:
        await message.reply_text("در حال حاضر دوره یا بازدید فعالی وجود ندارد. 📪")
        return
        
    buttons = [[InlineKeyboardButton(f"{event['title']} ({event['type']})", callback_data=f"event_{event['event_id']}")] for event in events]
    
    # اگر از دکمه 'بازگشت' استفاده شده، پیام قبلی را ویرایش کن
    if update.callback_query and update.callback_query.data == "back_to_events":
        await update.callback_query.message.edit_text(
            "رویدادهای فعال:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await message.reply_text(
            "رویدادهای فعال:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

async def event_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """جزئیات یک رویداد خاص را نمایش می‌دهد."""
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[1])
    
    event = await db.get_event_details(event_id)
            
    if not event:
        await query.message.reply_text("رویداد یافت نشد!")
        return
        
    if not event['is_active']:
        await query.message.edit_text(f"رویداد غیرفعال شده است. دلیل: {event['deactivation_reason']}")
        return
        
    capacity_text = "نامحدود" if event['type'] == "دوره" else f"{event['capacity'] - event['current_capacity']}/{event['capacity']}"
    cost_text = "رایگان" if event['cost'] == 0 else f"{event['cost']:,} تومان"
    
    text = (
        f"عنوان: {event['title']}\n"
        f"نوع: {event['type']}\n"
        f"تاریخ: {event['date']}\n"
        f"محل: {event['location']}\n"
        f"هزینه: {cost_text}\n"
        f"ظرفیت باقی‌مانده: {capacity_text}\n"
        f"توضیحات: {event['description']}"
    )
    buttons = [
        [InlineKeyboardButton("ثبت‌نام ✅", callback_data=f"register_{event_id}")],
        [InlineKeyboardButton("بازگشت 🔙", callback_data="back_to_events")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def register_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فرآیند ثبت‌نام در رویداد (رایگان یا پولی) را مدیریت می‌کند."""
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
    
    try:
        async with await db.get_db_connection() as conn:
            event = await db.get_event_details(event_id)
            user = await db.get_user_info(user_id)
            
            if not event or not user:
                await query.message.reply_text("خطا: اطلاعات رویداد یا کاربر یافت نشد. آیا پروفایل شما تکمیل است؟")
                return

            # بررسی تکرار ثبت‌نام
            async with conn.execute("SELECT * FROM registrations WHERE user_id = ? AND event_id = ?", (user_id, event_id)) as cursor:
                if await cursor.fetchone():
                    await query.message.reply_text("شما قبلاً ثبت‌نام کرده‌اید! 📋")
                    return
            
            if not event['is_active']:
                await query.message.reply_text(f"رویداد غیرفعال شده است. دلیل: {event['deactivation_reason']}")
                return
            
            # بررسی ظرفیت
            if event['type'] != "دوره" and event['current_capacity'] >= event['capacity']:
                await query.message.reply_text("ظرفیت تکمیل شده است. 📪")
                return

            # رویداد رایگان
            if event['cost'] == 0:
                await conn.execute(
                    "INSERT INTO registrations (user_id, event_id, registered_at) VALUES (?, ?, ?)",
                    (user_id, event_id, datetime.now().isoformat())
                )
                await conn.execute(
                    "UPDATE events SET current_capacity = current_capacity + 1 WHERE event_id = ?",
                    (event_id,)
                )
                
                async with conn.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,)) as cursor:
                    reg_count = (await cursor.fetchone())[0]
                
                await conn.commit()

                # ارسال اطلاعات ثبت‌نام به گروه اپراتور
                hashtag = f"#{event['type']} #{event['hashtag'].replace(' ', '_')}"
                text = (
                    f"{hashtag}\n{reg_count}:\n"
                    f"نام: {user['full_name']}\nکد ملی: {user['national_id']}\n"
                    f"شماره دانشجویی: {user['student_id']}\nشماره تماس: {user['phone']}"
                )
                message = await context.bot.send_message(OPERATOR_GROUP_ID, text)
                
                await conn.execute(
                    "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (message.message_id, OPERATOR_GROUP_ID, user_id, event_id, "registration", datetime.now().isoformat())
                )
                await conn.commit()

                await query.message.reply_text("ثبت‌نام شما با موفقیت انجام شد! ✅")
                
                # بررسی تکمیل ظرفیت بعد از ثبت‌نام
                if event['type'] != "دوره" and event['current_capacity'] + 1 >= event['capacity']:
                    await deactivate_event(event_id, "تکمیل ظرفیت", context)
            
            # رویداد پولی
            else:
                context.user_data["pending_event_id"] = event_id
                await query.message.reply_text(
                    f"برای تکمیل ثبت‌نام در {event['title']}، لطفاً مبلغ **{event['cost']:,} تومان** را به شماره کارت زیر واریز کنید:\n\n`{CARD_NUMBER}`\n\n"
                    f"سپس **تصویر رسید پرداخت** را در همین چت ارسال کنید. 📸"
                )

    except Exception as e:
        logger.error(f"Error during registration for user {user_id} event {event_id}: {e}")
        await query.message.reply_text("خطایی در فرآیند ثبت‌نام رخ داد. لطفاً دوباره تلاش کنید.")

async def handle_payment_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رسید پرداخت کاربر را دریافت و برای ادمین‌ها ارسال می‌کند."""
    if "pending_event_id" not in context.user_data:
        await update.message.reply_text("لطفاً ابتدا یک رویداد انتخاب کنید و فرآیند ثبت‌نام را آغاز کنید.")
        return
        
    event_id = context.user_data["pending_event_id"]
    user_id = update.effective_user.id
    
    try:
        async with await db.get_db_connection() as conn:
            event = await db.get_event_details(event_id)
            user = await db.get_user_info(user_id)
            
            if not event or not user:
                await update.message.reply_text("خطا: اطلاعات رویداد یا کاربر یافت نشد.")
                return

            text = (
                f"#{event['type']} #{event['hashtag'].replace(' ', '_')}\n"
                f"**درخواست تأیید پرداخت**\n"
                f"نام: {user['full_name']}\nکد ملی: {user['national_id']}\n"
                f"شماره دانشجویی: {user['student_id']}\nشماره تماس: {user['phone']}\n"
                f"مبلغ: {event['cost']:,} تومان"
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
            
            await conn.execute(
                "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message.message_id, OPERATOR_GROUP_ID, user_id, event_id, "payment", datetime.now().isoformat())
            )
            await conn.commit()
            
        await update.message.reply_text("رسید شما ارسال شد و در انتظار تأیید ادمین‌ها است. ✅")
        del context.user_data["pending_event_id"] # حذف حالت انتظار
        
    except Exception as e:
        logger.error(f"Error handling payment receipt for {user_id} event {event_id}: {e}")
        await update.message.reply_text("خطایی در ارسال رسید رخ داد. لطفاً دوباره تلاش کنید.")

async def payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت اقدامات ادمین (تأیید/ابطال) روی رسیدهای پرداخت."""
    query = update.callback_query
    
    if not await is_user_admin(update.effective_user.id):
        await query.answer("فقط ادمین‌ها می‌توانند این اقدام را انجام دهند! 🚫", show_alert=True)
        return

    await query.answer()
    callback_parts = query.data.split("_")
    action = callback_parts[0]

    # دکمه 'بازگشت' یا 'انجام شد' (برای حذف پیام ادمین)
    if action == "done":
        await query.message.delete()
        return

    try:
        # مدیریت دکمه‌های مرحله دوم (تأیید نهایی)
        if action == "confirm" and len(callback_parts) >= 5:
            sub_action = callback_parts[1]
            user_id = int(callback_parts[3])
            event_id = int(callback_parts[4])

            async with await db.get_db_connection() as conn:
                event = await db.get_event_details(event_id)
                user = await db.get_user_info(user_id)

                if not event or not user:
                    await query.message.edit_caption(caption="خطا: رویداد یا کاربر یافت نشد.")
                    return

                # اگر کاربر قبلا ثبت‌نام کرده، دوباره ثبت‌نام نکن
                async with conn.execute("SELECT * FROM registrations WHERE user_id = ? AND event_id = ?", (user_id, event_id)) as cursor:
                    if await cursor.fetchone():
                        await context.bot.send_message(user_id, "ثبت‌نام شما قبلاً تأیید و تکمیل شده بود! ✅")
                        await query.message.edit_caption(caption=f"{query.message.caption}\n\n**✅ قبلاً تأیید شده بود. **", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("حذف پیام", callback_data="done")]]))
                        return

                if sub_action == "confirm_payment":
                    # ثبت‌نام در جدول registrations
                    await conn.execute(
                        "INSERT INTO registrations (user_id, event_id, registered_at) VALUES (?, ?, ?)",
                        (user_id, event_id, datetime.now().isoformat())
                    )
                    # ثبت پرداخت در جدول payments
                    await conn.execute(
                        "INSERT INTO payments (user_id, event_id, amount, confirmed_at) VALUES (?, ?, ?, ?)",
                        (user_id, event_id, event['cost'], datetime.now().isoformat())
                    )
                    # به‌روزرسانی ظرفیت
                    await conn.execute(
                        "UPDATE events SET current_capacity = current_capacity + 1 WHERE event_id = ?",
                        (event_id,)
                    )
                    async with conn.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,)) as cursor:
                        reg_count = (await cursor.fetchone())[0]
                    await conn.commit()
                    
                    # ارسال لیست ثبت‌نام جدید به اپراتور
                    hashtag = f"#{event['type']} #{event['hashtag'].replace(' ', '_')}"
                    text = (
                        f"{hashtag}\n{reg_count}:\n"
                        f"نام: {user['full_name']}\nکد ملی: {user['national_id']}\n"
                        f"شماره دانشجویی: {user['student_id']}\nشماره تماس: {user['phone']}"
                    )
                    message_log = await context.bot.send_message(OPERATOR_GROUP_ID, text)
                    
                    # ثبت پیام لاگ در دیتابیس
                    await conn.execute(
                        "INSERT INTO operator_messages (message_id, chat_id, user_id, event_id, message_type, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (message_log.message_id, OPERATOR_GROUP_ID, user_id, event_id, "registration", datetime.now().isoformat())
                    )
                    await conn.commit()

                    await context.bot.send_message(user_id, f"پرداخت شما برای {event['title']} تأیید شد و ثبت‌نام شما تکمیل شد! ✅")
                    
                    # بررسی و غیرفعال کردن در صورت تکمیل ظرفیت
                    if event['type'] != "دوره" and event['current_capacity'] + 1 >= event['capacity']:
                        await deactivate_event(event_id, "تکمیل ظرفیت", context)
                        
                    await query.message.edit_caption(caption=f"{query.message.caption}\n\n**✅ توسط ادمین {update.effective_user.full_name} تأیید نهایی شد.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("حذف پیام", callback_data="done")]]))
                
                elif sub_action == "unclear_payment":
                    await context.bot.send_message(
                        user_id,
                        f"رسید تراکنش شما برای رویداد {event['title']} ناخوانا یا غیرقابل بررسی بود. لطفاً رسید تراکنش‌تون رو دوباره آپلود کنید."
                    )
                    await query.message.edit_caption(caption=f"{query.message.caption}\n\n**📸 توسط ادمین {update.effective_user.full_name} ناخوانا اعلام شد.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("حذف پیام", callback_data="done")]]))
                
                elif sub_action == "cancel_payment":
                    await context.bot.send_message(
                        user_id,
                        f"پرداخت شما برای رویداد {event['title']} تأیید نشد. لطفاً فرآیند ثبت‌نام را دوباره انجام دهید."
                    )
                    await query.message.edit_caption(caption=f"{query.message.caption}\n\n**🚫 توسط ادمین {update.effective_user.full_name} ابطال شد.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("حذف پیام", callback_data="done")]]))
        
        # مدیریت دکمه‌های مرحله اول (تأیید، ناخوانا، ابطال) - مرحله پیش از تأیید نهایی
        elif len(callback_parts) == 3 and action in ["confirm_payment", "unclear_payment", "cancel_payment"]:
            user_id = int(callback_parts[1])
            event_id = int(callback_parts[2])
            action_label = {
                "confirm_payment": "تأیید ✅",
                "unclear_payment": "ناخوانا 📸",
                "cancel_payment": "ابطال 🚫"
            }[action]
            
            # جلوگیری از انجام عملیات تکراری توسط ادمین‌های مختلف
            caption = query.message.caption
            if "تأیید نهایی شد" in caption or "ابطال شد" in caption:
                 await query.answer("این رسید قبلاً توسط ادمین دیگری پردازش شده است.", show_alert=True)
                 return

            # تغییر دکمه‌ها به دکمه تأیید نهایی
            buttons = [
                [InlineKeyboardButton(f"تأیید نهایی {action_label}", callback_data=f"confirm_{action}_{user_id}_{event_id}")],
                [InlineKeyboardButton("بازگشت", callback_data="done")]
            ]
            await query.message.edit_reply_markup(InlineKeyboardMarkup(buttons))
        
    except Exception as e:
        logger.error(f"Error processing payment action: {query.data}, error: {str(e)}")
        await query.message.reply_text("خطایی رخ داد. لطفاً دوباره تلاش کنید.")
