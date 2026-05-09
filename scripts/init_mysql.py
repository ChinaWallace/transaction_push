#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Initialize and verify the configured MySQL database.

This script connects to the MySQL server from DATABASE_URL, creates the target
database if needed, creates SQLAlchemy tables, and prints a small verification
summary. It intentionally does not use SQLite fallback.
"""

import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from app.core.config import get_settings  # noqa: E402


def _quote_identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError(f"Unsafe MySQL database name: {name!r}")
    return f"`{name}`"


def init_mysql() -> bool:
    settings = get_settings()
    url = make_url(settings.database_url)

    if url.get_backend_name() != "mysql":
        print(f"DATABASE_URL is not MySQL: {url.render_as_string(hide_password=True)}")
        return False

    if not url.database:
        print("DATABASE_URL must include a database name, for example /trading_db")
        return False

    database_name = url.database
    server_url = url.set(database="")
    connect_args = {
        "charset": "utf8mb4",
        "connect_timeout": settings.db_connect_timeout,
        "read_timeout": settings.db_read_timeout,
        "write_timeout": settings.db_write_timeout,
    }

    print(f"Connecting to MySQL server: {server_url.render_as_string(hide_password=True)}")
    server_engine = create_engine(server_url, connect_args=connect_args, pool_pre_ping=True)

    with server_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS {_quote_identifier(database_name)} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )

    server_engine.dispose()
    print(f"Database ready: {database_name}")

    # Import models before create_all so every table is registered on Base.metadata.
    import app.models  # noqa: F401, E402
    from app.core.database import Base, get_engine  # noqa: E402

    engine = get_engine()
    if engine is None:
        print("Application database engine is unavailable.")
        return False

    if engine.dialect.name != "mysql":
        print(f"Unexpected database dialect: {engine.dialect.name}")
        return False

    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        current_db = conn.execute(text("SELECT DATABASE()")).scalar()
        table_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
        ).scalar()

    print(f"Connected database: {current_db}")
    print(f"Tables available: {table_count}")
    print("MySQL initialization completed successfully.")
    return True


if __name__ == "__main__":
    try:
        raise SystemExit(0 if init_mysql() else 1)
    except Exception as exc:
        print(f"MySQL initialization failed: {exc}")
        raise SystemExit(1)
