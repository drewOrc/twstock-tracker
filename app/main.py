import logging
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":  # Chinese log lines on a cp950/cp1252 console
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import scheduler  # noqa: E402
from .api import auth_routes, crm_proxy, routes  # noqa: E402
from .config import BASE_DIR, settings  # noqa: E402
from .db import init_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
if settings.log_to_file:  # a service has no console: keep rotating logs under data/logs
    from logging.handlers import RotatingFileHandler

    _log_dir = BASE_DIR / "data" / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _fh = RotatingFileHandler(_log_dir / "engine.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

STATIC_DIR = BASE_DIR / "static"  # legacy vanilla dashboard, kept at /legacy
WEB_DIST = BASE_DIR / "web" / "dist"  # unified React frontend (npm run build)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)

# Same-origin in production (served from this process). CORS stays open for the Vite dev server;
# cookies are only sent cross-origin when allow_credentials is on, which we keep off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# namespaces: /api/market (通用層), /api/me (個人化層), /api/admin; legacy /api/* kept for compatibility
app.include_router(routes.public, prefix="/api")
app.include_router(auth_routes.router)
app.include_router(auth_routes.admin_router)
app.include_router(routes.market, prefix="/api/market")
app.include_router(routes.me, prefix="/api/me")
app.include_router(routes.admin, prefix="/api/admin")
app.include_router(routes.market, prefix="/api", include_in_schema=False)
app.include_router(routes.me, prefix="/api", include_in_schema=False)
app.include_router(routes.admin, prefix="/api", include_in_schema=False)
app.include_router(crm_proxy.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/legacy", StaticFiles(directory=STATIC_DIR, html=True), name="legacy")
if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


def _index() -> FileResponse:
    page = WEB_DIST / "index.html" if (WEB_DIST / "index.html").exists() else STATIC_DIR / "index.html"
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return _index()


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """Client-side routes of the React app resolve to index.html; unknown API paths stay 404."""
    if full_path.startswith(("api/", "static/", "legacy/", "assets/", "docs", "openapi.json", "redoc")):
        raise HTTPException(status_code=404, detail="Not Found")
    return _index()
