"""Production WSGI entry point used by Gunicorn."""

from src.application import PipelineRunner
from src.config import Settings
from src.dashboard import create_dashboard_app
from src.database import create_database_engine
from src.sources import build_registry, load_source_catalog

settings = Settings.from_env()
if not settings.database_url:
    raise RuntimeError("DATABASE_URL is required to start the dashboard")
catalog = load_source_catalog(settings.source_config_path)
engine = create_database_engine(settings.database_url)
runner = PipelineRunner(build_registry(catalog), catalog, engine=engine)
app = create_dashboard_app(engine, runner=runner)
