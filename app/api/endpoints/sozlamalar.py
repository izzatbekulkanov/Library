"""
app/api/endpoints/sozlamalar.py — Sozlamalar sahifasi va API endpointlari
"""
from __future__ import annotations

import os
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core import database as db_core
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.core.database import get_db
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from app.core.system_settings import (
    get_system_settings,
    is_book_delete_blocked,
    save_system_settings,
)
from app.models.library import (
    Author,
    BBK,
    Book,
    BookCopy,
    BookEdition,
    BookType,
    Library,
    OnlineBook,
    PublicationYear,
    PublishedCity,
    Publisher,
)
from app.models.user import User, UserTypeEnum

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
SYSTEM_UPLOAD_DIR = os.path.join("app", "static", "uploads", "system")
os.makedirs(SYSTEM_UPLOAD_DIR, exist_ok=True)


def _to_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _save_system_logo(upload, *, prefix: str) -> str | None:
    if not upload or not getattr(upload, "filename", ""):
        return None

    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        ext = ".png"
    name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    dst = os.path.join(SYSTEM_UPLOAD_DIR, name)
    with open(dst, "wb") as fh:
        shutil.copyfileobj(upload.file, fh)
    return f"/static/uploads/system/{name}"


def _base_ctx(request: Request, **extra):
    return {"request": request, "session_user": get_session_user(request), **extra}


def _ensure_access(request: Request) -> dict:
    session_user = get_session_user(request)
    if not session_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not can_access_menu(session_user, "sozlamalar"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return session_user


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def sozlamalar_index(request: Request, db: Session = Depends(get_db)):
    session_user = get_session_user(request)
    if not session_user:
        return RedirectResponse(url="/two_login", status_code=302)
    if not can_access_menu(session_user, "sozlamalar"):
        return RedirectResponse(url=build_menu_denied_url(session_user, "sozlamalar"), status_code=302)

    return templates.TemplateResponse(
        "sozlamalar.html",
        _base_ctx(request, title="Sozlamalar", active_menu="sozlamalar"),
    )


@router.get("/api/counts")
async def get_counts(request: Request, db: Session = Depends(get_db)):
    _ensure_access(request)
    online_count = db.query(OnlineBook).count()
    online_editions = db.query(BookEdition).count()
    printed_count = db.query(Book).count()
    printed_copies = db.query(BookCopy).count()
    authors_count = db.query(Author).count()
    book_types_count = db.query(BookType).count()
    bbk_count = db.query(BBK).count()
    publishers_count = db.query(Publisher).count()
    published_cities_count = db.query(PublishedCity).count()
    publication_years_count = db.query(PublicationYear).count()
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    staff_users = db.query(User).filter(
        or_(
            User.is_staff == True,
            User.user_type == UserTypeEnum.admin,
            User.user_type == UserTypeEnum.lib_staff,
            User.user_type == UserTypeEnum.lib_head,
        )
    ).count()
    total_libraries = db.query(Library).count()
    active_libraries = db.query(Library).filter(Library.active == True).count()
    return JSONResponse({
        "online_books": online_count,
        "online_editions": online_editions,
        "printed_books": printed_count,
        "printed_copies": printed_copies,
        "authors": authors_count,
        "book_types": book_types_count,
        "bbk": bbk_count,
        "publishers": publishers_count,
        "published_cities": published_cities_count,
        "publication_years": publication_years_count,
        "total_users": total_users,
        "active_users": active_users,
        "staff_users": staff_users,
        "total_libraries": total_libraries,
        "active_libraries": active_libraries,
    })


@router.get("/api/system-config")
async def get_system_config(request: Request):
    _ensure_access(request)
    return JSONResponse({
        "ok": True,
        **get_system_settings(force_reload=True),
    })


@router.post("/api/system-config")
async def save_system_config(request: Request):
    _ensure_access(request)
    form = await request.form()
    system_name = str(form.get("system_name") or "").strip()
    maintenance_message = str(form.get("maintenance_message") or "").strip()
    maintenance_mode = _to_bool(form.get("maintenance_mode"), False)
    block_book_delete = _to_bool(form.get("block_book_delete"), False)

    current = get_system_settings(force_reload=True)
    payload: dict[str, object] = {
        "maintenance_mode": maintenance_mode,
        "block_book_delete": block_book_delete,
        "maintenance_message": maintenance_message or current.get("maintenance_message"),
    }
    if system_name:
        payload["system_name"] = system_name

    large_logo = _save_system_logo(form.get("logo_large_file"), prefix="logo_large")
    small_logo = _save_system_logo(form.get("logo_small_file"), prefix="logo_small")
    if large_logo:
        payload["logo_large"] = large_logo
    if small_logo:
        payload["logo_small"] = small_logo

    saved = save_system_settings(payload)
    return JSONResponse({
        "ok": True,
        "message": "Tizim sozlamalari saqlandi.",
        "config": saved,
    })


@router.get("/api/db-config")
async def get_db_config(request: Request):
    _ensure_access(request)
    return JSONResponse({
        "ok": True,
        **db_core.get_database_config(mask_password=True),
    })


@router.post("/api/db-config")
async def save_db_config(request: Request):
    _ensure_access(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        prepared = db_core.build_database_config_from_payload(payload)
        applied = db_core.apply_database_config(prepared, persist=True)

        # Engine yangilangandan keyin jadval/ustunlarni kafolatlab qo'yamiz.
        from app.models import user as user_models  # noqa: WPS433
        from app.models import library as library_models  # noqa: F401,WPS433

        user_models.Base.metadata.create_all(bind=db_core.engine)
        db_core.ensure_book_copy_print_columns()
        db_core.ensure_user_menu_permissions_column()

        return JSONResponse({
            "ok": True,
            "message": "DB sozlamalari saqlandi va ulanish muvaffaqiyatli tekshirildi.",
            "config": applied,
        })
    except ValueError as exc:
        return JSONResponse(
            {"ok": False, "detail": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "detail": f"DB sozlamasini saqlashda xatolik: {str(exc)}"},
            status_code=500,
        )


@router.post("/api/db-config/test")
async def test_db_config(request: Request):
    _ensure_access(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        prepared = db_core.build_database_config_from_payload(payload)
        db_core.test_database_config(prepared)
        return JSONResponse({
            "ok": True,
            "message": "Ulanish muvaffaqiyatli tekshirildi.",
        })
    except ValueError as exc:
        return JSONResponse({"ok": False, "detail": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "detail": f"Ulanishni tekshirishda xatolik: {str(exc)}"},
            status_code=500,
        )


@router.post("/api/delete-all/{book_type}")
async def delete_all_books(book_type: str, request: Request, db: Session = Depends(get_db)):
    _ensure_access(request)
    if is_book_delete_blocked():
        return JSONResponse(
            {
                "ok": False,
                "detail": "Kitob o'chirish amali sozlamalarda taqiqlangan.",
            },
            status_code=403,
        )

    if book_type not in {"online", "printed"}:
        raise HTTPException(
            status_code=400,
            detail="Noto'g'ri kitob turi. 'online' yoki 'printed' bo'lishi kerak.",
        )

    try:
        if book_type == "online":
            # Faster path: avoid pre-count() full scans, use affected rows.
            edition_result = db.execute(text("DELETE FROM book_editions"))
            db.execute(text("DELETE FROM online_book_authors"))
            book_result = db.execute(text("DELETE FROM online_books"))
            db.commit()

            edition_count = max(int(edition_result.rowcount or 0), 0)
            book_count = max(int(book_result.rowcount or 0), 0)
            return JSONResponse({
                "ok": True,
                "message": (
                    f"{book_count} ta online kitob va "
                    f"{edition_count} ta versiyasi (edition) o'chirildi."
                ),
                "deleted_books": book_count,
                "deleted_editions": edition_count,
            })

        copy_result = db.execute(text("DELETE FROM book_copies"))
        db.execute(text("DELETE FROM book_authors"))
        book_result = db.execute(text("DELETE FROM books"))
        db.commit()

        copy_count = max(int(copy_result.rowcount or 0), 0)
        book_count = max(int(book_result.rowcount or 0), 0)
        return JSONResponse({
            "ok": True,
            "message": (
                f"{book_count} ta bosma kitob va "
                f"{copy_count} ta nusxasi (copy) o'chirildi."
            ),
            "deleted_books": book_count,
            "deleted_copies": copy_count,
        })
    except Exception as exc:
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "detail": f"O'chirishda xatolik: {exc}",
            },
            status_code=500,
        )
