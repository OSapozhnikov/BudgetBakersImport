from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.jobs import JobStore
from app.persistence.accounts_store import AccountsStore
from app.persistence.category_cache import CategoryCacheStore
from app.persistence.fingerprints import FingerprintStore
from app.persistence.import_history import ImportHistoryStore
from app.persistence.mapping_store import CategoryMappingStore
from app.persistence.prefs_store import PrefsStore
from app.routers.convert import convert_router
from app.routers.settings import settings_router
from app.settings import Settings, get_settings
from app.version import __version__

APP_DIR = Path(__file__).resolve().parent


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(title="BudgetBakers Excel → CSV", version=__version__)
    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    app.state.settings = settings
    app.state.templates = templates
    app.state.mapping_store = CategoryMappingStore(settings.data_dir)
    app.state.accounts_store = AccountsStore(settings.data_dir)
    app.state.fingerprint_store = FingerprintStore(settings.data_dir)
    app.state.history_store = ImportHistoryStore(settings.data_dir)
    app.state.prefs_store = PrefsStore(settings.data_dir)
    app.state.category_cache = CategoryCacheStore(settings.data_dir)
    app.state.jobs = JobStore()

    app.include_router(convert_router())
    app.include_router(settings_router())
    return app


app = create_app()
