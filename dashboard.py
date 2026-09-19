"""Start the product monitoring dashboard."""

from src.application import PipelineRunner
from src.config import Settings
from src.dashboard import create_dashboard_app
from src.database import create_database_engine, create_schema
from src.sources import build_registry, load_source_catalog
from src.utils.logging import configure_logging


def main() -> int:
    settings = Settings.from_env()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required to start the dashboard")
    configure_logging(settings.log_level)
    catalog = load_source_catalog(settings.source_config_path)
    engine = create_database_engine(settings.database_url)
    create_schema(engine)
    runner = PipelineRunner(build_registry(catalog), catalog, engine=engine)
    app = create_dashboard_app(engine, runner=runner, catalog_path=settings.source_config_path)
    app.run(host=settings.dashboard_host, port=settings.dashboard_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
