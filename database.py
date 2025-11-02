# database.py
import aiosqlite
import logging
from datetime import datetime, timedelta
from config import DB_PATH

logger = logging.getLogger(__name__)

async def init_db():
    """
    پایگاه داده را با تمام جداول لازم، از جمله جدول نظرسنجی، راه‌اندازی می‌کند.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys = ON;")
        
        # جدول کاربران
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, full_name TEXT,
                national_id TEXT, student_id TEXT, phone TEXT, created_at TEXT
            )
        """)
        
        # جدول رویدادها
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, type TEXT,
                date TEXT, location TEXT, capacity INTEGER,
                current_capacity INTEGER DEFAULT 0, description TEXT,
                is_active INTEGER DEFAULT 1, hashtag TEXT, cost INTEGER,
                card_number TEXT, deactivation_reason TEXT,
                feedback_sent_at TEXT -- ستون جدید برای سیستم نظرسنجی
            )
        """)
        
        # جدول ثبت‌نام‌ها
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, event_id INTEGER, registered_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            )
        """)
        
        # جدول پرداخت‌ها
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                event_id INTEGER, amount INTEGER, confirmed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            )
        """)
        
        # جدول ادمین‌ها
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY, added_at TEXT
            )
        """)
        
        # جدول پیام‌های اپراتور
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS operator_messages (
                message_id INTEGER PRIMARY KEY, chat_id INTEGER, user_id INTEGER,
                event_id INTEGER, message_type TEXT, sent_at TEXT
            )
        """)
        
        # جدول جدید برای امتیازدهی
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS event_ratings (
                rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, event_id INTEGER, rating INTEGER, submitted_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id),
                UNIQUE(user_id, event_id) -- هر کاربر فقط یکبار به هر رویداد رای می‌دهد
            )
        """)
        
        await conn.commit()
        await _check_and_add_feedback_column(conn)


async def _check_and_add_feedback_column(conn):
    """ستون feedback_sent_at را در صورت عدم وجود به جدول events اضافه می‌کند."""
    try:
        async with conn.execute("PRAGMA table_info(events)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if 'feedback_sent_at' not in columns:
            await conn.execute("ALTER TABLE events ADD COLUMN feedback_sent_at TEXT;")
            await conn.commit()
            logger.info("Column 'feedback_sent_at' added to 'events' table.")
    except aiosqlite.Error as e:
        logger.error(f"Error checking/adding column: {e}")

# --- توابع کمکی ---

async def get_db_connection():
    """یک اتصال پایگاه داده با row_factory تنظیم شده برمی‌گرداند."""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn

async def get_user_info(user_id: int) -> aiosqlite.Row | None:
    async with await get_db_connection() as conn:
        async with conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def get_admin_info(user_id: int) -> aiosqlite.Row | None:
    async with await get_db_connection() as conn:
        async with conn.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def get_event_details(event_id: int) -> aiosqlite.Row | None:
    async with await get_db_connection() as conn:
        async with conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)) as cursor:
            return await cursor.fetchone()

async def get_all_events() -> list[aiosqlite.Row]:
    async with await get_db_connection() as conn:
        async with conn.execute("SELECT * FROM events ORDER BY date DESC") as cursor:
            return await cursor.fetchall()

async def update_event_field(event_id: int, field: str, value) -> bool:
    """یک فیلد خاص از یک رویداد را به‌روزرسانی می‌کند."""
    # لیست سفید فیلدهای مجاز برای جلوگیری از SQL Injection
    allowed_fields = ['title', 'description', 'cost', 'date', 'location', 'capacity', 'hashtag', 'type']
    if field not in allowed_fields:
        logger.error(f"Attempt to update non-allowed field: {field}")
        return False
        
    query = f"UPDATE events SET {field} = ? WHERE event_id = ?"
    try:
        async with await get_db_connection() as conn:
            await conn.execute(query, (value, event_id))
            await conn.commit()
        return True
    except aiosqlite.Error as e:
        logger.error(f"Error updating event field {field} for event {event_id}: {e}")
        return False

# --- توابع سیستم نظرسنجی ---

async def get_recently_finished_events() -> list[aiosqlite.Row]:
    """رویدادهایی که تمام شده‌اند و هنوز نظرسنجی برایشان ارسال نشده را برمی‌گرداند."""
    # رویدادهایی که تاریخشان گذشته، غیرفعال هستند و نظرسنجی ارسال نشده
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    async with await get_db_connection() as conn:
        async with conn.execute(
            """
            SELECT event_id, title, type, date FROM events
            WHERE date <= ? AND is_active = 0 AND feedback_sent_at IS NULL
            ORDER BY date DESC
            """, (yesterday,)
        ) as cursor:
            return await cursor.fetchall()

async def get_event_participants(event_id: int) -> list[aiosqlite.Row]:
    """لیست شرکت‌کنندگان یک رویداد را برمی‌گرداند."""
    async with await get_db_connection() as conn:
        async with conn.execute("SELECT user_id FROM registrations WHERE event_id = ?", (event_id,)) as cursor:
            return await cursor.fetchall()

async def set_feedback_sent(event_id: int):
    """زمان ارسال نظرسنجی را در دیتابیس ثبت می‌کند."""
    try:
        async with await get_db_connection() as conn:
            await conn.execute(
                "UPDATE events SET feedback_sent_at = ? WHERE event_id = ?",
                (datetime.now().isoformat(), event_id)
            )
            await conn.commit()
    except aiosqlite.Error as e:
        logger.error(f"Error setting feedback_sent_at for event {event_id}: {e}")

async def get_event_feedback_status(event_id: int) -> aiosqlite.Row | None:
    """وضعیت ارسال نظرسنجی (زمان ارسال) را برمی‌گرداند."""
    async with await get_db_connection() as conn:
        async with conn.execute("SELECT feedback_sent_at FROM events WHERE event_id = ?", (event_id,)) as cursor:
            return await cursor.fetchone()

async def store_rating(user_id: int, event_id: int, rating: int):
    """امتیاز کاربر را ثبت یا به‌روزرسانی می‌کند."""
    try:
        async with await get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO event_ratings (user_id, event_id, rating, submitted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, event_id) DO UPDATE SET
                    rating = excluded.rating,
                    submitted_at = excluded.submitted_at
                """,
                (user_id, event_id, rating, datetime.now().isoformat())
            )
            await conn.commit()
    except aiosqlite.Error as e:
        logger.error(f"Error storing rating for user {user_id}, event {event_id}: {e}")

async def get_event_ratings(event_id: int) -> aiosqlite.Row | None:
    """میانگین و تعداد امتیازات یک رویداد را محاسبه می‌کند."""
    async with await get_db_connection() as conn:
        async with conn.execute(
            "SELECT AVG(rating) as avg_rating, COUNT(rating) as num_ratings FROM event_ratings WHERE event_id = ?",
            (event_id,)
        ) as cursor:
            return await cursor.fetchone()
