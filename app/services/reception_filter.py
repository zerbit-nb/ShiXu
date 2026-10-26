"""Local exact-reply filter. Preserve originals and reuse reversible inbox trash."""
from app.database import utc_now

REPLIES = frozenset({'收到', '已收到', '好的', '好哒', '嗯', '嗯嗯', '谢谢', '谢谢啦', '谢谢了', '哈哈', '哈哈哈', 'ok', 'okay'})


def is_trivial_reply(text):
    # No substring, keyword-absence or semantic guesses. Questions and multiline
    # messages stay visible even if they contain a familiar acknowledgement.
    if not isinstance(text, str) or '\n' in text or '\r' in text:
        return False
    return text.strip().rstrip('。.!！~～').lower() in REPLIES


def enabled(db):
    return bool(db.conn.execute('SELECT enabled FROM reception_filter_settings WHERE id=1').fetchone()[0])


def apply_filter(db, message_id, text):
    """Called inside the original message/receipt transaction; never commits."""
    if enabled(db) and is_trivial_reply(text):
        db.conn.execute('INSERT INTO message_trash (message_id, trashed_at) VALUES (?, ?)', (message_id, utc_now()))
