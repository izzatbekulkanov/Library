from datetime import date, datetime, timedelta
import os
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from starlette import status as http_status

from app.core.auth import (
    MENU_ITEMS,
    build_menu_denied_url,
    can_access_menu,
    get_session_user,
    is_admin_session,
    normalize_menu_permissions,
    parse_menu_permissions,
    require_login,
    serialize_menu_permissions,
    set_session,
)
from app.core.database import get_db
from app.models.user import GenderEnum, User, UserTypeEnum

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
_CTX = {"active_menu": "users"}


def _guard(request: Request, menu_key: str = "users", require_admin: bool = True):
    login_redirect = require_login(request)
    if login_redirect:
        return login_redirect
    session_user = get_session_user(request)
    if menu_key and not can_access_menu(session_user, menu_key):
        return RedirectResponse(
            url=build_menu_denied_url(session_user, menu_key),
            status_code=http_status.HTTP_302_FOUND,
        )
    if require_admin and not is_admin_session(session_user):
        return RedirectResponse(
            url=build_menu_denied_url(session_user, menu_key),
            status_code=http_status.HTTP_302_FOUND,
        )
    return None


def _ctx(request: Request, **extra):
    return {
        "request": request,
        "session_user": get_session_user(request),
        "menu_items": MENU_ITEMS,
        **_CTX,
        **extra,
    }


def _add_page(request: Request, error: str | None = None, selected_menu_keys: list[str] | None = None):
    selected = selected_menu_keys or normalize_menu_permissions(None, is_staff=False, is_verified=False)
    return templates.TemplateResponse(
        "add_user.html",
        _ctx(
            request,
            title="Foydalanuvchi Qo'shish",
            error=error,
            selected_menu_keys=selected,
        ),
    )


def _edit_page(
    request: Request,
    user: User,
    error: str | None = None,
    selected_menu_keys: list[str] | None = None,
):
    selected = selected_menu_keys or normalize_menu_permissions(
        getattr(user, "menu_permissions", None),
        is_staff=bool(user.is_staff),
        is_verified=bool(user.is_verified),
    )
    return templates.TemplateResponse(
        "edit_user.html",
        _ctx(
            request,
            title="Foydalanuvchini Tahrirlash",
            user=user,
            error=error,
            selected_menu_keys=selected,
        ),
    )


@router.get("/", response_class=HTMLResponse)
async def get_users_page(request: Request, db: Session = Depends(get_db)):
    g = _guard(request)
    if g:
        return g
    now = datetime.utcnow()
    online_window = timedelta(minutes=2)

    def _dt_text(value):
        if not value:
            return "-"
        try:
            return value.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(value)

    users = db.query(User).order_by(User.id).all()
    for row in users:
        is_online_now = False
        if row.is_active and row.last_activity:
            try:
                is_online_now = (now - row.last_activity) <= online_window
            except Exception:
                is_online_now = False
        row.is_online_now = bool(is_online_now)
        row.last_activity_text = _dt_text(row.last_activity)

    return templates.TemplateResponse(
        "users.html",
        _ctx(request, title="Barcha Foydalanuvchilar", users=users),
    )


@router.get("/add", response_class=HTMLResponse)
async def add_user_page(request: Request):
    g = _guard(request)
    if g:
        return g
    return _add_page(request)


@router.post("/add")
async def process_add_user(request: Request, db: Session = Depends(get_db)):
    g = _guard(request)
    if g:
        return g
    try:
        form = await request.form()
        username = (form.get("username") or "").strip()
        email = (form.get("email") or "").strip()
        password = (form.get("password") or "").strip()
        selected_menu_keys = parse_menu_permissions(form.getlist("menu_permissions"))

        if not username or not email or not password:
            return _add_page(request, "Username, email va parol majburiy!", selected_menu_keys)

        exists = db.query(User).filter((User.username == username) | (User.email == email)).first()
        if exists:
            return _add_page(request, "Bu username yoki email allaqachon ro'yxatdan o'tgan.", selected_menu_keys)

        gender_val = form.get("gender", "")
        user_type_val = form.get("user_type", "")
        system_role = form.get("system_role", "user")
        is_staff = system_role in ("staff", "superadmin")
        is_verified = system_role == "superadmin"
        menu_permissions = normalize_menu_permissions(
            selected_menu_keys,
            is_staff=is_staff,
            is_verified=is_verified,
        )

        new_user = User(
            username=username,
            full_name=(form.get("full_name") or "").strip() or None,
            email=email,
            phone_number=(form.get("phone_number") or "").strip() or None,
            gender=next((g for g in GenderEnum if g.value == gender_val), None),
            user_type=next((ut for ut in UserTypeEnum if ut.value == user_type_val), None),
            is_active=form.get("is_active") == "on",
            is_staff=is_staff,
            is_verified=is_verified,
            hashed_password=User.get_password_hash(password),
            password_save=password,
            menu_permissions=serialize_menu_permissions(menu_permissions),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        name = new_user.full_name or new_user.username
        return RedirectResponse(
            url=f"/users?flash_type=success&flash_title=Foydalanuvchi+qo%27shildi&flash_msg={urllib.parse.quote(name + ' tizimga muvaffaqiyatli kiritildi.')}",
            status_code=http_status.HTTP_302_FOUND,
        )
    except Exception as exc:
        db.rollback()
        return _add_page(request, f"Server xatosi: {type(exc).__name__}: {str(exc)[:200]}")


@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    g = _guard(request)
    if g:
        return g
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(
            url="/users?flash_type=error&flash_msg=Foydalanuvchi+topilmadi",
            status_code=http_status.HTTP_302_FOUND,
        )
    return _edit_page(request, user)


@router.post("/{user_id}/edit")
async def process_edit_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    g = _guard(request)
    if g:
        return g
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(
            url="/users?flash_type=error&flash_msg=Foydalanuvchi+topilmadi",
            status_code=http_status.HTTP_302_FOUND,
        )

    try:
        form = await request.form()
        username = (form.get("username") or "").strip()
        email = (form.get("email") or "").strip()
        selected_menu_keys = parse_menu_permissions(form.getlist("menu_permissions"))
        if not username or not email:
            return _edit_page(request, user, "Username va email majburiy!", selected_menu_keys)

        dup = db.query(User).filter(
            ((User.username == username) | (User.email == email)) & (User.id != user_id)
        ).first()
        if dup:
            return _edit_page(request, user, "Bu username yoki email boshqa foydalanuvchida bor.", selected_menu_keys)

        gender_val = form.get("gender", "")
        user_type_val = form.get("user_type", "")
        system_role = form.get("system_role", "user")
        is_staff = system_role in ("staff", "superadmin")
        is_verified = system_role == "superadmin"
        menu_permissions = normalize_menu_permissions(
            selected_menu_keys,
            is_staff=is_staff,
            is_verified=is_verified,
        )

        user.username = username
        user.full_name = (form.get("full_name") or "").strip() or None
        user.short_name = (form.get("short_name") or "").strip() or None
        user.first_name = (form.get("first_name") or "").strip() or None
        user.second_name = (form.get("second_name") or "").strip() or None
        user.third_name = (form.get("third_name") or "").strip() or None
        user.email = email
        user.phone_number = (form.get("phone_number") or "").strip() or None
        user.hemis_id = (form.get("hemis_id") or "").strip() or None
        user.telegram = (form.get("telegram") or "").strip() or None
        user.instagram = (form.get("instagram") or "").strip() or None
        user.facebook = (form.get("facebook") or "").strip() or None
        user.year_of_enter = (form.get("year_of_enter") or "").strip() or None

        age_val = (form.get("age") or "").strip()
        user.age = int(age_val) if age_val.isdigit() else None

        bd_str = (form.get("birth_date") or "").strip()
        if bd_str:
            try:
                user.birth_date = date.fromisoformat(bd_str)
            except ValueError:
                pass
        else:
            user.birth_date = None

        user.gender = next((g for g in GenderEnum if g.value == gender_val), None)
        user.user_type = next((ut for ut in UserTypeEnum if ut.value == user_type_val), None)
        user.is_active = form.get("is_active") == "on"
        user.is_followers_book = form.get("is_followers_book") == "on"
        user.is_staff = is_staff
        user.is_verified = is_verified
        user.menu_permissions = serialize_menu_permissions(menu_permissions)

        password = (form.get("password") or "").strip()
        if password:
            user.hashed_password = User.get_password_hash(password)
            user.password_save = password

        image_file = form.get("image")
        if image_file and hasattr(image_file, "filename") and image_file.filename:
            upload_dir = os.path.join("app", "static", "uploads", "avatars")
            os.makedirs(upload_dir, exist_ok=True)
            ext = os.path.splitext(image_file.filename)[1] or ".jpg"
            fname = f"user_{user_id}_{uuid.uuid4().hex[:8]}{ext}"
            fpath = os.path.join(upload_dir, fname)
            with open(fpath, "wb") as f:
                f.write(await image_file.read())
            user.image = f"/static/uploads/avatars/{fname}"

        db.commit()
        session_user = get_session_user(request)
        if session_user and session_user.get("id") == user.id:
            # O'zini tahrirlagan holatda sessiyadagi rol/ruxsatlarni ham yangilash
            set_session(request, user)
        name = user.full_name or user.username
        return RedirectResponse(
            url="/users?flash_type=success&flash_title=Saqlandi&flash_msg=" + urllib.parse.quote(name + " ma'lumotlari yangilandi."),
            status_code=http_status.HTTP_302_FOUND,
        )
    except Exception as exc:
        db.rollback()
        return _edit_page(request, user, f"Server xatosi: {type(exc).__name__}: {str(exc)[:200]}")


@router.post("/{user_id}/delete")
async def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    g = _guard(request)
    if g:
        return g
    session_user = get_session_user(request)
    if session_user and session_user.get("id") == user_id:
        return RedirectResponse(
            url="/users?flash_type=error&flash_msg=O%27zingizni%20o%27chirib%20bo%27lmaydi",
            status_code=http_status.HTTP_302_FOUND,
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        name = user.full_name or user.username
        db.delete(user)
        db.commit()
        return RedirectResponse(
            url="/users?flash_type=success&flash_title=O%27chirildi&flash_msg=" + urllib.parse.quote(name + " tizimdan o'chirildi."),
            status_code=http_status.HTTP_302_FOUND,
        )

    return RedirectResponse(
        url="/users?flash_type=error&flash_msg=Foydalanuvchi+topilmadi",
        status_code=http_status.HTTP_302_FOUND,
    )
