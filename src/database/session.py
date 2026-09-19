"""Database engine and schema initialization."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from .models import Base


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)

