from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from starlette import status as http_status
from app.core.database import get_db
from app.core.auth import (
    build_menu_denied_url,
    can_access_menu,
    clear_session,
    default_menu_permissions,
    first_accessible_path,
    get_session_user,
    menu_key_from_path,
    set_session,
)
from app.models.user import User, UserTypeEnum
from app.models.library import Book, BookCopy, OnlineBook, Library

router    = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _base_ctx(request: Request, **extra):
    return {"request": request, "session_user": get_session_user(request), **extra}


def _has_any_user(db: Session) -> bool:
    return db.query(User.id).first() is not None


# ════════════ TWO LOGIN (kirish usuli tanlash) ════════════
@router.get("/two_login", response_class=HTMLResponse)
async def two_login_page(request: Request, db: Session = Depends(get_db)):
    if get_session_user(request):
        return RedirectResponse(url="/", status_code=http_status.HTTP_302_FOUND)
    if not _has_any_user(db):
        return RedirectResponse(url="/setup", status_code=http_status.HTTP_302_FOUND)
    flash_type    = request.query_params.get("flash_type", "")
    flash_title   = request.query_params.get("flash_title", "")
    flash_message = request.query_params.get("flash_msg", "")
    return templates.TemplateResponse("two_login.html", {
        "request": request,
        "flash_type": flash_type, "flash_title": flash_title, "flash_message": flash_message,
    })


# ════════════ LOGIN (parol bilan) ═════════════
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    if get_session_user(request):
        return RedirectResponse(url="/", status_code=http_status.HTTP_302_FOUND)
    if not _has_any_user(db):
        return RedirectResponse(url="/setup", status_code=http_status.HTTP_302_FOUND)
    next_url = request.query_params.get("next", "/")
    return templates.TemplateResponse("login.html", {"request": request, "next": next_url})


@router.post("/login", response_class=HTMLResponse)
async def process_login(request: Request, db: Session = Depends(get_db)):
    form_data = await request.form()
    username  = (form_data.get("username") or "").strip()
    password  = (form_data.get("password") or "").strip()
    next_url  = form_data.get("next", "/") or "/"

    if not _has_any_user(db):
        return RedirectResponse(url="/setup", status_code=http_status.HTTP_302_FOUND)

    def _err(msg):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": msg, "next": next_url, "username": username},
            status_code=200,
        )

    if not username:
        return _err("Foydalanuvchi nomini kiriting.")
    if not password:
        return _err("Parolni kiriting.")

    user = db.query(User).filter(
        (User.username == username) | (User.email == username)
    ).first()

    if not user:
        return _err("Bunday foydalanuvchi topilmadi. Username yoki emailni tekshiring.")
    if not user.is_active:
        return _err("Ushbu hisob bloklangan. Administrator bilan bog'laning.")

    try:
        ok = user.verify_password(password)
    except Exception:
        return _err("Parolni tekshirishda xato yuz berdi.")

    if not ok:
        return _err("Parol noto'g'ri. Qayta urinib ko'ring.")

    set_session(request, user)
    session_user = get_session_user(request)

    user.last_login = datetime.utcnow()
    db.commit()

    safe_next = next_url if next_url.startswith("/") else "/"
    next_menu = menu_key_from_path(safe_next)
    if next_menu and not can_access_menu(session_user, next_menu):
        safe_next = first_accessible_path(session_user)

    return RedirectResponse(
        url=safe_next,
        status_code=http_status.HTTP_302_FOUND,
    )


# ════════════ DC LOGIN (placeholder) ═════════
@router.get("/login/dc", response_class=HTMLResponse)
async def dc_login_page(request: Request, db: Session = Depends(get_db)):
    if get_session_user(request):
        return RedirectResponse(url="/", status_code=http_status.HTTP_302_FOUND)
    if not _has_any_user(db):
        return RedirectResponse(url="/setup", status_code=http_status.HTTP_302_FOUND)
    return templates.TemplateResponse("login.html", {
        "request": request, "next": "/",
        "error": "DC integratsiyasi hali sozlanmagan. Parol bilan kiring.",
    })


@router.get("/setup", response_class=HTMLResponse)
async def first_setup_page(request: Request, db: Session = Depends(get_db)):
    if _has_any_user(db):
        if get_session_user(request):
            return RedirectResponse(url="/", status_code=http_status.HTTP_302_FOUND)
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)

    return templates.TemplateResponse("first_setup.html", {"request": request})


@router.post("/setup", response_class=HTMLResponse)
async def first_setup_submit(request: Request, db: Session = Depends(get_db)):
    if _has_any_user(db):
        if get_session_user(request):
            return RedirectResponse(url="/", status_code=http_status.HTTP_302_FOUND)
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)

    form_data = await request.form()
    full_name = (form_data.get("full_name") or "").strip()
    username = (form_data.get("username") or "").strip()
    email = (form_data.get("email") or "").strip()
    password = (form_data.get("password") or "").strip()
    password_confirm = (form_data.get("password_confirm") or "").strip()

    def _render_error(msg: str):
        return templates.TemplateResponse(
            "first_setup.html",
            {
                "request": request,
                "error": msg,
                "full_name": full_name,
                "username": username,
                "email": email,
            },
            status_code=200,
        )

    if not full_name:
        return _render_error("To'liq ismni kiriting.")
    if not username:
        return _render_error("Username kiriting.")
    if not email:
        return _render_error("Email kiriting.")
    if not password:
        return _render_error("Parol kiriting.")
    if len(password) < 6:
        return _render_error("Parol kamida 6 ta belgidan iborat bo'lishi kerak.")
    if password != password_confirm:
        return _render_error("Parollar mos emas.")

    duplicate = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    if duplicate:
        return _render_error("Username yoki email allaqachon mavjud.")

    try:
        first_user = User(
            full_name=full_name,
            username=username,
            email=email,
            hashed_password=User.get_password_hash(password),
            password_save=password,
            user_type=UserTypeEnum.admin,
            is_staff=True,
            is_verified=True,
            is_active=True,
            menu_permissions=",".join(
                default_menu_permissions(is_staff=True, is_verified=True)
            ),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_login=datetime.utcnow(),
        )
        db.add(first_user)
        db.commit()
        db.refresh(first_user)
    except Exception:
        db.rollback()
        return _render_error("Foydalanuvchini yaratishda xatolik yuz berdi.")

    set_session(request, first_user)
    return RedirectResponse(url="/", status_code=http_status.HTTP_302_FOUND)


# ════════════ LOGOUT ══════════════════════════
@router.get("/logout")
async def logout(request: Request):
    clear_session(request)
    return templates.TemplateResponse("logout.html", {"request": request})


# ════════════ BOSH SAHIFA ═════════════════════
@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request, db: Session = Depends(get_db)):
    session_user = get_session_user(request)
    if not session_user:
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)
    if not can_access_menu(session_user, "dashboard"):
        return RedirectResponse(
            url=build_menu_denied_url(session_user, "dashboard"),
            status_code=http_status.HTTP_302_FOUND,
        )

    from app.models.library import BookType
    
    total_print_books = db.query(func.count(Book.id)).scalar() or 0
    total_online_books = db.query(func.count(OnlineBook.id)).scalar() or 0
    total_copies = db.query(func.count(BookCopy.id)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
    active_libraries = db.query(func.count(Library.id)).filter(Library.active == True).scalar() or 0
    passive_libraries = db.query(func.count(Library.id)).filter(Library.active == False).scalar() or 0

    # Chart data: Book Types distribution
    book_types_dist = db.query(BookType.name, func.count(Book.id)).outerjoin(Book, Book.book_type_id == BookType.id).group_by(BookType.name).all()
    # Chart data: Copies distribution by Library
    library_dist = db.query(Library.name, func.count(BookCopy.id)).outerjoin(BookCopy, BookCopy.library_id == Library.id).group_by(Library.name).all()

    book_type_labels = [row[0] for row in book_types_dist if row[1] > 0]
    book_type_counts = [row[1] for row in book_types_dist if row[1] > 0]
    lib_labels = [row[0] for row in library_dist if row[1] > 0]
    lib_counts = [row[1] for row in library_dist if row[1] > 0]

    return templates.TemplateResponse(
        "index.html",
        _base_ctx(
            request,
            title="Bosh Sahifa",
            active_menu="dashboard",
            stats={
                "total_print_books": total_print_books,
                "total_online_books": total_online_books,
                "total_copies": total_copies,
                "total_users": total_users,
                "active_users": active_users,
                "active_libraries": active_libraries,
                "passive_libraries": passive_libraries,
                "book_type_labels": book_type_labels,
                "book_type_counts": book_type_counts,
                "lib_labels": lib_labels,
                "lib_counts": lib_counts,
            },
        ),
    )


@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: Session = Depends(get_db)):
    session_user = get_session_user(request)
    if not session_user:
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)
    if not can_access_menu(session_user, "about"):
        return RedirectResponse(
            url=build_menu_denied_url(session_user, "about"),
            status_code=http_status.HTTP_302_FOUND,
        )
    user = db.query(User).filter(User.id == session_user.get("id")).first()
    if not user:
        clear_session(request)
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)

    def _enum_text(value, fallback: str = "-") -> str:
        if value is None:
            return fallback
        return getattr(value, "value", str(value))

    def _dt_text(value) -> str:
        if not value:
            return "-"
        try:
            return value.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(value)

    def _d_text(value) -> str:
        if not value:
            return "-"
        try:
            return value.strftime("%d.%m.%Y")
        except Exception:
            return str(value)

    now = datetime.utcnow()
    is_online_now = False
    if user.is_active and user.last_activity:
        try:
            is_online_now = (now - user.last_activity) <= timedelta(minutes=2)
        except Exception:
            is_online_now = False

    about = {
        "id": user.id,
        "image": user.image or "",
        "full_name": user.full_name or user.username or "User",
        "username": user.username or "-",
        "short_name": user.short_name or "-",
        "first_name": user.first_name or "-",
        "second_name": user.second_name or "-",
        "third_name": user.third_name or "-",
        "gender": _enum_text(user.gender),
        "birth_date": _d_text(user.birth_date),
        "age": user.age if user.age is not None else "-",
        "email": user.email or "-",
        "phone_number": user.phone_number or "-",
        "telegram": user.telegram or "-",
        "instagram": user.instagram or "-",
        "facebook": user.facebook or "-",
        "hemis_id": user.hemis_id or "-",
        "user_type": _enum_text(user.user_type, "User"),
        "role_label": "Super Admin" if user.is_verified else ("Admin" if user.is_staff else "User"),
        "status_text": "Faol" if user.is_active else "Nofaol",
        "verify_text": "Tasdiqlangan" if user.is_verified else "Tasdiqlanmagan",
        "year_of_enter": user.year_of_enter or "-",
        "followers_book": "Ha" if user.is_followers_book else "Yo'q",
        "last_login": _dt_text(user.last_login),
        "last_activity": _dt_text(user.last_activity),
        "created_at": _dt_text(user.created_at),
        "updated_at": _dt_text(user.updated_at),
        "is_active": bool(user.is_active),
        "is_online_now": bool(is_online_now),
        "online_text": "Onlayn (hozir tizimda)" if is_online_now else "Offlayn",
        "online_hint": "Oxirgi 2 daqiqa ichida faol" if is_online_now else "Hozir tizimdan foydalanmayapti",
    }

    return templates.TemplateResponse(
        "about.html",
        _base_ctx(request, title="Men haqimda", active_menu="about", about=about),
    )


@router.get("/privacy-policy", response_class=HTMLResponse)
@router.get("/privacy-policy/", response_class=HTMLResponse)
@router.get("/privacy", response_class=HTMLResponse)
@router.get("/privacy/", response_class=HTMLResponse)
async def privacy_policy_page(request: Request):
    session_user = get_session_user(request)
    if not session_user:
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)
    if not can_access_menu(session_user, "about"):
        return RedirectResponse(
            url=build_menu_denied_url(session_user, "about"),
            status_code=http_status.HTTP_302_FOUND,
        )
    return templates.TemplateResponse(
        "privacy_policy.html",
        _base_ctx(request, title="Maxfiylik siyosati", active_menu="privacy_policy"),
    )


@router.get("/help", response_class=HTMLResponse)
@router.get("/help/", response_class=HTMLResponse)
@router.get("/yordam", response_class=HTMLResponse)
@router.get("/yordam/", response_class=HTMLResponse)
async def help_page(request: Request):
    session_user = get_session_user(request)
    if not session_user:
        return RedirectResponse(url="/two_login", status_code=http_status.HTTP_302_FOUND)
    if not can_access_menu(session_user, "about"):
        return RedirectResponse(
            url=build_menu_denied_url(session_user, "about"),
            status_code=http_status.HTTP_302_FOUND,
        )
    return templates.TemplateResponse(
        "help.html",
        _base_ctx(request, title="Yordam bo'limi", active_menu="help"),
    )


@router.get("/online_books")
@router.get("/online_books/")
async def online_books_compat_redirect():
    return RedirectResponse(url="/online-books", status_code=http_status.HTTP_302_FOUND)
