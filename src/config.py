"""Environment-driven application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    default_source_id: str = "books-demo"
    source_config_path: Path = Path("config/sources.json")
    output_path: Path = Path("data/products.csv")
    max_pages: int = 0
    database_url: str | None = None
    scheduler_timezone: str = "UTC"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        defaults = cls()
        return cls(
            default_source_id=os.getenv("DEFAULT_SOURCE_ID", defaults.default_source_id),
            source_config_path=Path(
                os.getenv("SOURCE_CONFIG_PATH", str(defaults.source_config_path))
            ),
            output_path=Path(
                os.getenv("OUTPUT_PATH", str(defaults.output_path))
            ),
            max_pages=int(os.getenv("SOURCE_MAX_PAGES", str(defaults.max_pages))),
            database_url=os.getenv("DATABASE_URL") or None,
            scheduler_timezone=os.getenv(
                "SCHEDULER_TIMEZONE", defaults.scheduler_timezone
            ),
            log_level=os.getenv("LOG_LEVEL", defaults.log_level),
        )
