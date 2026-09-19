"""Database engine and schema initialization."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text

from .models import Base


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        statements = (
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS monitoring_settings JSONB NOT NULL DEFAULT '{}'::jsonb",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS timeout_seconds NUMERIC(10,3) NOT NULL DEFAULT 10",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 3",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS backoff_factor NUMERIC(10,3) NOT NULL DEFAULT 0.5",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS monitoring_settings JSONB NOT NULL DEFAULT '{}'::jsonb",
        )
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
