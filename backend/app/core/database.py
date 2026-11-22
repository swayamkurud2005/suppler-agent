"""
SQLAlchemy async engine and session factory configured for PostgreSQL (Neon-ready).
Falls back to local SQLite database when PostgreSQL is unavailable.
"""

import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.core.config import settings

logger = logging.getLogger("database")

SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///./supplier360.db"


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def _create_engine_for_url(db_url: str):
    connect_args = {}
    is_sqlite = "sqlite" in db_url

    if "asyncpg" in db_url:
        connect_args["timeout"] = 10.0
        if "neon.tech" in db_url or "ssl=require" in db_url or "sslmode=require" in db_url:
            connect_args["ssl"] = "require"

    if is_sqlite:
        connect_args["check_same_thread"] = False

    # Remove query string params asyncpg doesn't understand (ssl*, channel_binding)
    clean_url = db_url
    if "?" in clean_url and "asyncpg" in clean_url:
        base_part, query_part = clean_url.split("?", 1)
        # Keep only params that asyncpg actually supports
        params = [p for p in query_part.split("&") if not p.startswith("ssl") and not p.startswith("channel_binding")]
        clean_url = f"{base_part}?{'&'.join(params)}" if params else base_part

    kwargs = dict(
        echo=settings.DEBUG,
        connect_args=connect_args,
    )
    # SQLite doesn't support pool_size / max_overflow
    if not is_sqlite:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20

    return create_async_engine(clean_url, **kwargs)


_current_url = settings.async_database_url
engine = _create_engine_for_url(_current_url)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def ensure_active_engine():
    """Verify database connection; fall back to SQLite if PostgreSQL is unreachable."""
    global engine, async_session_factory, _current_url

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return engine
    except Exception as e:
        safe_url = _current_url.split("@")[-1] if "@" in _current_url else _current_url
        logger.warning(
            f"[DATABASE] PostgreSQL unreachable at '{safe_url}': {e}. "
            f"Falling back to local SQLite database (supplier360.db)."
        )
        _current_url = SQLITE_FALLBACK_URL
        engine = _create_engine_for_url(SQLITE_FALLBACK_URL)
        async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return engine


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an active database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
