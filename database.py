"""
PostgreSQL database layer using psycopg2-binary.
All public functions are async — sync DB calls run in a thread pool via asyncio.to_thread.
psycopg2-binary has pre-built wheels for every Python version, zero compilation needed.
"""
import asyncio
import os
import psycopg2
import psycopg2.extras
import psycopg2.pool
import psycopg2.errors
from typing import Optional, List, Dict

DATABASE_URL = os.getenv("DATABASE_URL", "")
_pool: psycopg2.pool.ThreadedConnectionPool = None


# ── Connection pool ────────────────────────────────────────────────────────────

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL)
    return _pool


def _exec(sql: str, params=None, fetch: str = None):
    """Synchronous execute — runs in thread pool."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            if fetch == "one":
                return dict(cur.fetchone()) if cur.rowcount != 0 else None
            if fetch == "all":
                return [dict(r) for r in cur.fetchall()]
            if fetch == "scalar":
                row = cur.fetchone()
                return list(row.values())[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


async def _run(sql: str, params=None, fetch: str = None):
    """Async wrapper — offloads _exec to thread pool."""
    return await asyncio.to_thread(_exec, sql, params, fetch)


# ── Init ───────────────────────────────────────────────────────────────────────

def _init_sync():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id     BIGINT PRIMARY KEY,
                    username    TEXT,
                    added_by    BIGINT,
                    added_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id              SERIAL PRIMARY KEY,
                    type            TEXT NOT NULL,
                    channel         TEXT,
                    discussion_link TEXT,
                    amount          TEXT NOT NULL,
                    description     TEXT,
                    end_time        TIMESTAMPTZ NOT NULL,
                    created_by      BIGINT NOT NULL,
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    status          TEXT DEFAULT 'running',
                    message_id      BIGINT,
                    chat_id         BIGINT,
                    winner_id       BIGINT,
                    winner_username TEXT,
                    entry_count     INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id          SERIAL PRIMARY KEY,
                    giveaway_id INTEGER NOT NULL,
                    user_id     BIGINT NOT NULL,
                    username    TEXT,
                    full_name   TEXT,
                    joined_at   TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(giveaway_id, user_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS captcha_sessions (
                    token       TEXT PRIMARY KEY,
                    user_id     BIGINT NOT NULL,
                    giveaway_id INTEGER NOT NULL,
                    answer      TEXT NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    attempts    INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_message_counts (
                    giveaway_id INTEGER NOT NULL,
                    user_id     BIGINT NOT NULL,
                    username    TEXT,
                    msg_count   INTEGER DEFAULT 0,
                    PRIMARY KEY(giveaway_id, user_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inline_shares (
                    giveaway_id INTEGER NOT NULL,
                    user_id     BIGINT NOT NULL,
                    share_count INTEGER DEFAULT 0,
                    PRIMARY KEY(giveaway_id, user_id)
                )
            """)
    finally:
        conn.autocommit = False
        pool.putconn(conn)


async def init_db():
    await asyncio.to_thread(_init_sync)


# ── Admin ──────────────────────────────────────────────────────────────────────

async def add_admin(user_id: int, username: str, added_by: int) -> bool:
    try:
        await _run(
            "INSERT INTO admins (user_id, username, added_by) VALUES (%s,%s,%s)",
            (user_id, username, added_by)
        )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


async def remove_admin(user_id: int) -> bool:
    def _do():
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM admins WHERE user_id=%s", (user_id,))
                count = cur.rowcount
                conn.commit()
                return count > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
    return await asyncio.to_thread(_do)


async def get_admins() -> List[Dict]:
    return await _run("SELECT * FROM admins ORDER BY added_at DESC", fetch="all") or []


async def is_admin(user_id: int) -> bool:
    row = await _run("SELECT 1 FROM admins WHERE user_id=%s", (user_id,), fetch="one")
    return row is not None


# ── Giveaway ───────────────────────────────────────────────────────────────────

async def create_giveaway(data: Dict) -> int:
    from datetime import datetime
    end_time = datetime.fromisoformat(data["end_time"])
    def _do():
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO giveaways
                       (type, channel, discussion_link, amount, description, end_time, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (data["type"], data.get("channel"), data.get("discussion_link"),
                     data["amount"], data.get("description"), end_time, data["created_by"])
                )
                row = cur.fetchone()
                conn.commit()
                return row[0]
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
    return await asyncio.to_thread(_do)


async def update_giveaway_post(gw_id: int, message_id: int, chat_id: int):
    await _run(
        "UPDATE giveaways SET message_id=%s, chat_id=%s WHERE id=%s",
        (message_id, chat_id, gw_id)
    )


async def delete_giveaway(gw_id: int):
    await _run("DELETE FROM giveaways WHERE id=%s", (gw_id,))
    await _run("DELETE FROM entries WHERE giveaway_id=%s", (gw_id,))
    await _run("DELETE FROM user_message_counts WHERE giveaway_id=%s", (gw_id,))
    await _run("DELETE FROM inline_shares WHERE giveaway_id=%s", (gw_id,))

async def get_giveaway(gw_id: int) -> Optional[Dict]:
    return await _run("SELECT * FROM giveaways WHERE id=%s", (gw_id,), fetch="one")


async def get_running_giveaways() -> List[Dict]:
    return await _run(
        "SELECT * FROM giveaways WHERE status='running' ORDER BY created_at DESC",
        fetch="all"
    ) or []


async def end_giveaway(gw_id: int, winner_id: int, winner_username: str):
    await _run(
        "UPDATE giveaways SET status='ended', winner_id=%s, winner_username=%s WHERE id=%s",
        (winner_id, winner_username, gw_id)
    )


async def update_entry_count(gw_id: int, count: int):
    await _run("UPDATE giveaways SET entry_count=%s WHERE id=%s", (count, gw_id))


# ── Entries ────────────────────────────────────────────────────────────────────

async def add_entry(gw_id: int, user_id: int, username: str, full_name: str) -> bool:
    try:
        await _run(
            "INSERT INTO entries (giveaway_id, user_id, username, full_name) VALUES (%s,%s,%s,%s)",
            (gw_id, user_id, username, full_name)
        )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


async def has_entered(gw_id: int, user_id: int) -> bool:
    row = await _run(
        "SELECT 1 FROM entries WHERE giveaway_id=%s AND user_id=%s", (gw_id, user_id), fetch="one"
    )
    return row is not None


async def get_entry_count(gw_id: int) -> int:
    val = await _run(
        "SELECT COUNT(*) FROM entries WHERE giveaway_id=%s", (gw_id,), fetch="scalar"
    )
    return val or 0


async def get_all_entries(gw_id: int) -> List[Dict]:
    return await _run("SELECT * FROM entries WHERE giveaway_id=%s", (gw_id,), fetch="all") or []


# ── Captcha ────────────────────────────────────────────────────────────────────

async def save_captcha(token: str, user_id: int, gw_id: int, answer: str):
    await _run(
        "DELETE FROM captcha_sessions WHERE user_id=%s AND giveaway_id=%s", (user_id, gw_id)
    )
    await _run(
        "INSERT INTO captcha_sessions (token, user_id, giveaway_id, answer) VALUES (%s,%s,%s,%s)",
        (token, user_id, gw_id, answer)
    )


async def get_captcha(token: str) -> Optional[Dict]:
    return await _run("SELECT * FROM captcha_sessions WHERE token=%s", (token,), fetch="one")


async def increment_captcha_attempts(token: str) -> int:
    def _do():
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE captcha_sessions SET attempts=attempts+1 WHERE token=%s RETURNING attempts",
                    (token,)
                )
                row = cur.fetchone()
                conn.commit()
                return row[0] if row else 0
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
    return await asyncio.to_thread(_do)


async def delete_captcha(token: str):
    await _run("DELETE FROM captcha_sessions WHERE token=%s", (token,))


# ── Message counts (Strict GW) ─────────────────────────────────────────────────

async def increment_msg_count(gw_id: int, user_id: int, username: str):
    await _run(
        """INSERT INTO user_message_counts (giveaway_id, user_id, username, msg_count)
           VALUES (%s,%s,%s,1)
           ON CONFLICT (giveaway_id, user_id) DO UPDATE SET msg_count=user_message_counts.msg_count+1""",
        (gw_id, user_id, username)
    )


async def get_top_texters(gw_id: int, top_percent: float = 0.10) -> List[Dict]:
    rows = await _run(
        """SELECT umc.user_id, umc.username, umc.msg_count
           FROM user_message_counts umc
           JOIN entries e ON e.user_id=umc.user_id AND e.giveaway_id=umc.giveaway_id
           WHERE umc.giveaway_id=%s ORDER BY umc.msg_count DESC""",
        (gw_id,), fetch="all"
    ) or []
    top_n = max(1, int(len(rows) * top_percent))
    return rows[:top_n]


# ── Inline share tracking ──────────────────────────────────────────────────────

async def increment_inline_share(gw_id: int, user_id: int) -> int:
    def _do():
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO inline_shares (giveaway_id, user_id, share_count)
                       VALUES (%s,%s,1)
                       ON CONFLICT (giveaway_id, user_id)
                       DO UPDATE SET share_count=inline_shares.share_count+1
                       RETURNING share_count""",
                    (gw_id, user_id)
                )
                row = cur.fetchone()
                conn.commit()
                return row[0] if row else 0
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
    return await asyncio.to_thread(_do)


async def get_inline_share_count(gw_id: int, user_id: int) -> int:
    val = await _run(
        "SELECT share_count FROM inline_shares WHERE giveaway_id=%s AND user_id=%s",
        (gw_id, user_id), fetch="scalar"
    )
    return val or 0
