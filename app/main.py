from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi import Request
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from datetime import datetime, timedelta
from app.api.routes import router
from app.api.endpoints.external_books import shutdown_import_workers, startup_import_workers
from app.core.auth import get_session_user
from app.core.config import settings
from app.core.database import SessionLocal, bootstrap_database_runtime
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from app.core.system_settings import get_system_settings
from app.models import user
from app.models.user import User
from app.models import library  # noqa: F401 — jadvallar create_all uchun

# Barcha jadvallarni yaratish (allaqachon bor bo'lsa o'tkazib yuboradi)
bootstrap_database_runtime()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=settings.openapi_url,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
    root_path=settings.ROOT_PATH or "",
)
templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def track_user_last_activity(request, call_next):
    try:
        path = request.url.path or "/"
        if not path.startswith("/static"):
            system_settings = get_system_settings()
            if bool(system_settings.get("maintenance_mode", False)):
                session_user = get_session_user(request)
                is_admin = bool(
                    session_user
                    and (session_user.get("is_staff") or session_user.get("is_verified"))
                )

                allowed_paths = {"/login", "/two_login", "/login/dc", "/logout", "/setup", "/health", "/healthz"}
                is_allowed = (
                    path in allowed_paths
                    or path.startswith("/static/")
                    or path.startswith("/setup/")
                    or path.startswith("/login/")
                )

                if not is_admin and not is_allowed:
                    maintenance_message = str(
                        system_settings.get("maintenance_message")
                        or "Tizimda texnik ishlar olib borilmoqda."
                    )
                    if path.startswith("/api/"):
                        return JSONResponse(
                            {
                                "ok": False,
                                "detail": maintenance_message,
                                "maintenance_mode": True,
                            },
                            status_code=503,
                        )
                    return templates.TemplateResponse(
                        "maintenance.html",
                        {
                            "request": request,
                            "maintenance_message": maintenance_message,
                        },
                        status_code=503,
                    )
    except Exception:
        pass

    response = await call_next(request)
    try:
        # Static yoki authdan tashqari odatiy so'rovlarda faollikni yangilab boramiz.
        if request.url.path.startswith("/static"):
            return response

        user_id = request.session.get("user_id")
        if not user_id:
            return response

        now = datetime.utcnow()
        last_touch_raw = request.session.get("last_activity_touch")
        should_touch = True
        if isinstance(last_touch_raw, str):
            try:
                last_touch = datetime.fromisoformat(last_touch_raw)
                should_touch = (now - last_touch) >= timedelta(seconds=30)
            except Exception:
                should_touch = True

        if should_touch:
            db = SessionLocal()
            try:
                db_user = db.query(User).filter(User.id == int(user_id)).first()
                if db_user:
                    db_user.last_activity = now
                    db.commit()
            finally:
                db.close()
            request.session["last_activity_touch"] = now.isoformat()
    except Exception:
        # activity tracking xatosi asosiy so'rovni to'xtatmasligi kerak
        pass
    return response

# ── Session Middleware (login uchun zarur) ──────────────────────────
# SECRET_KEY .env dan olinishi tavsiya qilinadi
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.APP_SESSION_SECRET_KEY,
    session_cookie=settings.APP_SESSION_COOKIE,
    max_age=settings.APP_SESSION_MAX_AGE,
    same_site=settings.APP_SESSION_SAME_SITE,
    https_only=settings.APP_SESSION_HTTPS_ONLY,
    domain=settings.APP_SESSION_DOMAIN,
)
if settings.APP_FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)
if settings.trusted_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

# ── Statik fayllar ─────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ── APIRouterlarni ulash ────────────────────────────────────────────
app.include_router(router)

from app.api.endpoints import router as endpoints_router
app.include_router(endpoints_router)


@app.get("/health", include_in_schema=False)
async def healthcheck():
    return {
        "ok": True,
        "status": "healthy",
        "env": settings.APP_ENV,
        "time": datetime.utcnow().isoformat(),
    }


@app.get("/healthz", include_in_schema=False)
async def healthcheck_alias():
    return await healthcheck()


def _is_api_path(request: Request) -> bool:
    return (request.url.path or "").startswith("/api/")


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if _is_api_path(request):
        return JSONResponse({"detail": "Sahifa topilmadi."}, status_code=404)
    return templates.TemplateResponse(
        "404.html",
        {
            "request": request,
            "detail": "Sahifa topilmadi.",
        },
        status_code=404,
    )


@app.on_event("startup")
async def _startup_external_import_workers():
    await startup_import_workers()


@app.on_event("shutdown")
async def _shutdown_external_import_workers():
    await shutdown_import_workers()
