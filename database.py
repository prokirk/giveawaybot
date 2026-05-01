"""PostgreSQL database layer using asyncpg (Neon-compatible)."""
import asyncpg
import os
from datetime import datetime
from typing import Optional, List, Dict

DATABASE_URL = os.getenv("DATABASE_URL", "")
_pool: asyncpg.Pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id     BIGINT PRIMARY KEY,
                username    TEXT,
                added_by    BIGINT,
                added_at    TIMESTAMPTZ DEFAULT NOW()
            );

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
            );

            CREATE TABLE IF NOT EXISTS entries (
                id          SERIAL PRIMARY KEY,
                giveaway_id INTEGER NOT NULL,
                user_id     BIGINT NOT NULL,
                username    TEXT,
                full_name   TEXT,
                joined_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(giveaway_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS captcha_sessions (
                token       TEXT PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                giveaway_id INTEGER NOT NULL,
                answer      TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                attempts    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_message_counts (
                giveaway_id INTEGER NOT NULL,
                user_id     BIGINT NOT NULL,
                username    TEXT,
                msg_count   INTEGER DEFAULT 0,
                PRIMARY KEY(giveaway_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS share_refs (
                token       TEXT PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                giveaway_id INTEGER NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(referrer_id, giveaway_id)
            );

            CREATE TABLE IF NOT EXISTS share_clicks (
                id          SERIAL PRIMARY KEY,
                ref_token   TEXT NOT NULL,
                clicker_id  BIGINT NOT NULL,
                clicked_at  TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(ref_token, clicker_id)
            );
        """)


# ── Admin ──────────────────────────────────────────────────────────────────────

async def add_admin(user_id: int, username: str, added_by: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO admins (user_id, username, added_by) VALUES ($1,$2,$3)",
                user_id, username, added_by
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def remove_admin(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM admins WHERE user_id=$1", user_id)
        return result != "DELETE 0"


async def get_admins() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM admins ORDER BY added_at DESC")
        return [dict(r) for r in rows]


async def is_admin(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM admins WHERE user_id=$1", user_id)
        return row is not None


# ── Giveaway ───────────────────────────────────────────────────────────────────

async def create_giveaway(data: Dict) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO giveaways
               (type, channel, discussion_link, amount, description, end_time, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            data["type"], data.get("channel"), data.get("discussion_link"),
            data["amount"], data.get("description"),
            datetime.fromisoformat(data["end_time"]), data["created_by"]
        )
        return row["id"]


async def update_giveaway_post(gw_id: int, message_id: int, chat_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE giveaways SET message_id=$1, chat_id=$2 WHERE id=$3",
            message_id, chat_id, gw_id
        )


async def get_giveaway(gw_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM giveaways WHERE id=$1", gw_id)
        return dict(row) if row else None


async def get_running_giveaways() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM giveaways WHERE status='running' ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


async def end_giveaway(gw_id: int, winner_id: int, winner_username: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE giveaways SET status='ended', winner_id=$1, winner_username=$2 WHERE id=$3",
            winner_id, winner_username, gw_id
        )


async def update_entry_count(gw_id: int, count: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE giveaways SET entry_count=$1 WHERE id=$2", count, gw_id
        )


# ── Entries ────────────────────────────────────────────────────────────────────

async def add_entry(gw_id: int, user_id: int, username: str, full_name: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO entries (giveaway_id, user_id, username, full_name) VALUES ($1,$2,$3,$4)",
                gw_id, user_id, username, full_name
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def has_entered(gw_id: int, user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM entries WHERE giveaway_id=$1 AND user_id=$2", gw_id, user_id
        )
        return row is not None


async def get_entry_count(gw_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM entries WHERE giveaway_id=$1", gw_id
        )
        return row["cnt"] if row else 0


async def get_all_entries(gw_id: int) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM entries WHERE giveaway_id=$1", gw_id)
        return [dict(r) for r in rows]


# ── Captcha ────────────────────────────────────────────────────────────────────

async def save_captcha(token: str, user_id: int, gw_id: int, answer: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM captcha_sessions WHERE user_id=$1 AND giveaway_id=$2",
            user_id, gw_id
        )
        await conn.execute(
            "INSERT INTO captcha_sessions (token, user_id, giveaway_id, answer) VALUES ($1,$2,$3,$4)",
            token, user_id, gw_id, answer
        )


async def get_captcha(token: str) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM captcha_sessions WHERE token=$1", token)
        return dict(row) if row else None


async def increment_captcha_attempts(token: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE captcha_sessions SET attempts=attempts+1 WHERE token=$1", token
        )
        row = await conn.fetchrow(
            "SELECT attempts FROM captcha_sessions WHERE token=$1", token
        )
        return row["attempts"] if row else 0


async def delete_captcha(token: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM captcha_sessions WHERE token=$1", token)


# ── Message counts (Strict GW) ─────────────────────────────────────────────────

async def increment_msg_count(gw_id: int, user_id: int, username: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_message_counts (giveaway_id, user_id, username, msg_count)
               VALUES ($1,$2,$3,1)
               ON CONFLICT (giveaway_id, user_id) DO UPDATE SET msg_count=user_message_counts.msg_count+1""",
            gw_id, user_id, username
        )


async def get_top_texters(gw_id: int, top_percent: float = 0.10) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT umc.user_id, umc.username, umc.msg_count
               FROM user_message_counts umc
               JOIN entries e ON e.user_id=umc.user_id AND e.giveaway_id=umc.giveaway_id
               WHERE umc.giveaway_id=$1 ORDER BY umc.msg_count DESC""",
            gw_id
        )
        all_users = [dict(r) for r in rows]
        top_n = max(1, int(len(all_users) * top_percent))
        return all_users[:top_n]


# ── Share refs ─────────────────────────────────────────────────────────────────

async def get_or_create_ref_token(user_id: int, gw_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT token FROM share_refs WHERE referrer_id=$1 AND giveaway_id=$2",
            user_id, gw_id
        )
        if row:
            return row["token"]
        import uuid
        token = "r" + uuid.uuid4().hex[:15]
        await conn.execute(
            "INSERT INTO share_refs (token, referrer_id, giveaway_id) VALUES ($1,$2,$3)",
            token, user_id, gw_id
        )
        return token


async def get_ref_info(token: str) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM share_refs WHERE token=$1", token)
        return dict(row) if row else None


async def add_share_click(ref_token: str, clicker_id: int) -> bool:
    """Returns True if this is a new unique click."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO share_clicks (ref_token, clicker_id) VALUES ($1,$2)",
                ref_token, clicker_id
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def count_share_clicks(ref_token: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM share_clicks WHERE ref_token=$1", ref_token
        )
        return row["cnt"] if row else 0
