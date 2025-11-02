import aiosqlite
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List, Any
from config import DB_PATH

logger = logging.getLogger(__name__)

# ثابت‌های پایگاه داده
ALLOWED_UPDATE_FIELDS = {
    'title', 'description', 'cost', 'date', 'location', 
    'capacity', 'hashtag', 'type', 'is_active'
}

SQL_SCHEMAS = {
    'users': """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            national_id TEXT,
            student_id TEXT,
            phone TEXT,
            created_at TEXT NOT NULL
        )
    """,
    'events': """
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT,
            date TEXT NOT NULL,
            location TEXT,
            capacity INTEGER,
            current_capacity INTEGER DEFAULT 0,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            hashtag TEXT,
            cost INTEGER DEFAULT 0,
            card_number TEXT,
            deactivation_reason TEXT,
            feedback_sent_at TEXT
        )
    """,
    'registrations': """
        CREATE TABLE IF NOT EXISTS registrations (
            registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            registered_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE,
            UNIQUE(user_id, event_id)
        )
    """,
    'payments': """
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            confirmed_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
        )
    """,
    'admins': """
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """,
    'operator_messages': """
        CREATE TABLE IF NOT EXISTS operator_messages (
            message_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            event_id INTEGER,
            message_type TEXT,
            sent_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
        )
    """,
    'event_ratings': """
        CREATE TABLE IF NOT EXISTS event_ratings (
            rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            submitted_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE,
            UNIQUE(user_id, event_id)
        )
    """
}


@asynccontextmanager
async def get_db_connection():
    """Context manager برای اتصال امن به پایگاه داده."""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()


async def init_db() -> None:
    """پایگاه داده را با تمام جداول لازم راه‌اندازی می‌کند."""
    async with get_db_connection() as conn:
        try:
            # تنظیمات پایگاه داده
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            
            # ایجاد تمام جداول
            for table_name, schema in SQL_SCHEMAS.items():
                await conn.execute(schema)
                logger.info(f"Table '{table_name}' initialized successfully")
            
            await conn.commit()
            await _ensure_columns(conn)
            
        except aiosqlite.Error as e:
            logger.error(f"Error initializing database: {e}")
            raise


async def _ensure_columns(conn: aiosqlite.Connection) -> None:
    """ستون‌های جدید را در صورت نیاز اضافه می‌کند."""
    try:
        # بررسی و اضافه کردن ستون feedback_sent_at
        async with conn.execute("PRAGMA table_info(events)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        
        if 'feedback_sent_at' not in columns:
            await conn.execute("ALTER TABLE events ADD COLUMN feedback_sent_at TEXT;")
            await conn.commit()
            logger.info("Column 'feedback_sent_at' added to events table")
            
    except aiosqlite.Error as e:
        logger.error(f"Error ensuring columns: {e}")


async def get_user_info(user_id: int) -> Optional[aiosqlite.Row]:
    """اطلاعات کاربر را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            async with conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                return await cursor.fetchone()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return None


async def get_admin_info(user_id: int) -> Optional[aiosqlite.Row]:
    """اطلاعات ادمین را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            async with conn.execute(
                "SELECT * FROM admins WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                return await cursor.fetchone()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching admin {user_id}: {e}")
        return None


async def get_event_details(event_id: int) -> Optional[aiosqlite.Row]:
    """جزئیات رویداد را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            async with conn.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event_id,)
            ) as cursor:
                return await cursor.fetchone()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching event {event_id}: {e}")
        return None


async def get_all_events(active_only: bool = False) -> List[aiosqlite.Row]:
    """تمام رویدادها را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            query = "SELECT * FROM events"
            params = []
            
            if active_only:
                query += " WHERE is_active = 1"
            
            query += " ORDER BY date DESC"
            
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchall()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching all events: {e}")
        return []


async def update_event_field(event_id: int, field: str, value: Any) -> bool:
    """یک فیلد خاص از رویداد را به‌روزرسانی می‌کند."""
    if field not in ALLOWED_UPDATE_FIELDS:
        logger.warning(f"Attempt to update non-allowed field: {field}")
        return False
    
    if not isinstance(event_id, int) or event_id <= 0:
        logger.warning(f"Invalid event_id: {event_id}")
        return False
    
    try:
        async with get_db_connection() as conn:
            query = f"UPDATE events SET {field} = ? WHERE event_id = ?"
            await conn.execute(query, (value, event_id))
            await conn.commit()
            logger.info(f"Updated event {event_id}: {field} = {value}")
            return True
    except aiosqlite.Error as e:
        logger.error(f"Error updating event {event_id} field {field}: {e}")
        return False


async def get_recently_finished_events() -> List[aiosqlite.Row]:
    """رویدادهای تمام‌شده‌ای که نظرسنجی برایشان ارسال نشده را برمی‌گرداند."""
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        async with get_db_connection() as conn:
            async with conn.execute(
                """
                SELECT event_id, title, type, date 
                FROM events
                WHERE date <= ? AND is_active = 0 AND feedback_sent_at IS NULL
                ORDER BY date DESC
                """,
                (yesterday,)
            ) as cursor:
                return await cursor.fetchall()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching recently finished events: {e}")
        return []


async def get_event_participants(event_id: int) -> List[aiosqlite.Row]:
    """شرکت‌کنندگان یک رویداد را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            async with conn.execute(
                "SELECT user_id FROM registrations WHERE event_id = ?",
                (event_id,)
            ) as cursor:
                return await cursor.fetchall()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching participants for event {event_id}: {e}")
        return []


async def set_feedback_sent(event_id: int) -> bool:
    """زمان ارسال نظرسنجی را در دیتابیس ثبت می‌کند."""
    try:
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE events SET feedback_sent_at = ? WHERE event_id = ?",
                (datetime.now().isoformat(), event_id)
            )
            await conn.commit()
            logger.info(f"Marked feedback as sent for event {event_id}")
            return True
    except aiosqlite.Error as e:
        logger.error(f"Error setting feedback_sent_at for event {event_id}: {e}")
        return False


async def get_event_feedback_status(event_id: int) -> Optional[aiosqlite.Row]:
    """وضعیت ارسال نظرسنجی رویداد را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            async with conn.execute(
                "SELECT feedback_sent_at FROM events WHERE event_id = ?",
                (event_id,)
            ) as cursor:
                return await cursor.fetchone()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching feedback status for event {event_id}: {e}")
        return None


async def store_rating(user_id: int, event_id: int, rating: int) -> bool:
    """امتیاز کاربر را ثبت یا به‌روزرسانی می‌کند."""
    if not (1 <= rating <= 5):
        logger.warning(f"Invalid rating value: {rating}")
        return False
    
    try:
        async with get_db_connection() as conn:
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
            logger.info(f"Stored rating {rating} from user {user_id} for event {event_id}")
            return True
    except aiosqlite.Error as e:
        logger.error(f"Error storing rating for user {user_id}, event {event_id}: {e}")
        return False


async def get_event_ratings(event_id: int) -> Optional[aiosqlite.Row]:
    """میانگین و تعداد امتیازات یک رویداد را برمی‌گرداند."""
    try:
        async with get_db_connection() as conn:
            async with conn.execute(
                """
                SELECT 
                    AVG(rating) as avg_rating, 
                    COUNT(rating) as num_ratings 
                FROM event_ratings 
                WHERE event_id = ?
                """,
                (event_id,)
            ) as cursor:
                return await cursor.fetchone()
    except aiosqlite.Error as e:
        logger.error(f"Error fetching ratings for event {event_id}: {e}")
        return None