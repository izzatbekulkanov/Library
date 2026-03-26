"""
app/core/auth.py — Session asosida auth dependency va helper funksiyalar
"""
from __future__ import annotations

import re
import urllib.parse

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette import status


MENU_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "Dashboard", "/"),
    ("users", "Foydalanuvchilar", "/users"),
    ("libraries", "Kutubxonalar", "/libraries"),
    ("book_types", "Kitob turlari", "/book_types"),
    ("authors", "Mualliflar", "/authors"),
    ("publishers", "Nashriyotlar", "/publishers"),
    ("books", "Kitoblar", "/books"),
    ("online_books", "Online kitoblar", "/online-books"),
    ("external_books", "Tashqi baza", "/external-books"),
    ("reports", "Hisobotlar", "/reports"),
    ("sozlamalar", "Sozlamalar", "/sozlamalar"),
    ("about", "Men haqimda", "/about"),
)
MENU_KEYS = tuple(item[0] for item in MENU_ITEMS)
MENU_PATHS = {key: path for key, _, path in MENU_ITEMS}


def default_menu_permissions(is_staff: bool = False, is_verified: bool = False) -> list[str]:
    if is_staff or is_verified:
        return list(MENU_KEYS)
    return ["dashboard", "books", "online_books", "reports", "about"]


def parse_menu_permissions(raw) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, str):
        chunks = re.split(r"[,\s]+", raw.strip())
    elif isinstance(raw, (list, tuple, set)):
        chunks = [str(x).strip() for x in raw if str(x).strip()]
    else:
        chunks = []

    picked = set(chunks)
    return [key for key in MENU_KEYS if key in picked]


def normalize_menu_permissions(raw, is_staff: bool = False, is_verified: bool = False) -> list[str]:
    perms = parse_menu_permissions(raw)
    if not perms:
        perms = default_menu_permissions(is_staff=is_staff, is_verified=is_verified)

    if is_staff or is_verified:
        if "users" not in perms:
            perms = [key for key in MENU_KEYS if key in (set(perms) | {"users"})]
        return perms

    # Foydalanuvchilar bo'limi faqat admin/superadmin uchun.
    perms = [key for key in perms if key != "users"]
    if not perms:
        perms = default_menu_permissions(is_staff=False, is_verified=False)
    return perms


def serialize_menu_permissions(raw) -> str | None:
    perms = parse_menu_permissions(raw)
    return ",".join(perms) if perms else None


def is_admin_session(session_user: dict | None) -> bool:
    if not session_user:
        return False
    return bool(session_user.get("is_staff") or session_user.get("is_verified"))


def first_accessible_path(session_user: dict | None) -> str:
    if not session_user:
        return "/"
    allowed = normalize_menu_permissions(
        session_user.get("menu_permissions"),
        is_staff=bool(session_user.get("is_staff")),
        is_verified=bool(session_user.get("is_verified")),
    )
    for key, _, path in MENU_ITEMS:
        if key in allowed:
            return path
    return "/about"


def can_access_menu(session_user: dict | None, menu_key: str | None) -> bool:
    if not session_user:
        return False
    if not menu_key:
        return True
    allowed = normalize_menu_permissions(
        session_user.get("menu_permissions"),
        is_staff=bool(session_user.get("is_staff")),
        is_verified=bool(session_user.get("is_verified")),
    )
    return menu_key in allowed


def menu_key_from_path(path: str) -> str | None:
    p = (path or "").strip()
    if not p:
        return None
    if p == "/":
        return "dashboard"
    for key, _, base_path in MENU_ITEMS:
        if key == "dashboard":
            continue
        if p == base_path or p.startswith(base_path + "/"):
            return key
    return None


def build_menu_denied_url(session_user: dict | None, menu_key: str | None = None) -> str:
    target = first_accessible_path(session_user)
    msg = "Ushbu bo'limga kirish huquqi sizda mavjud emas."
    sep = "&" if "?" in target else "?"
    return f"{target}{sep}flash_type=error&flash_msg={urllib.parse.quote(msg)}"


# ── Session kalitlari ──────────────────────────────────────────────
SESSION_USER_ID = "user_id"
SESSION_USERNAME = "username"
SESSION_IS_STAFF = "is_staff"
SESSION_IS_VERIFIED = "is_verified"
SESSION_FULL_NAME = "full_name"
SESSION_IMAGE = "image"
SESSION_ROLE_LABEL = "role_label"
SESSION_MENU_PERMISSIONS = "menu_permissions"


def get_session_user(request: Request) -> dict | None:
    """Session dan foydalanuvchi ma'lumotlarini olish.
    Agar session yo'q bo'lsa — None qaytaradi."""
    user_id = request.session.get(SESSION_USER_ID)
    if not user_id:
        return None
    is_staff = bool(request.session.get(SESSION_IS_STAFF, False))
    is_verified = bool(request.session.get(SESSION_IS_VERIFIED, False))
    menu_permissions = normalize_menu_permissions(
        request.session.get(SESSION_MENU_PERMISSIONS),
        is_staff=is_staff,
        is_verified=is_verified,
    )
    return {
        "id": user_id,
        "username": request.session.get(SESSION_USERNAME, ""),
        "full_name": request.session.get(SESSION_FULL_NAME, ""),
        "image": request.session.get(SESSION_IMAGE, ""),
        "role_label": request.session.get(SESSION_ROLE_LABEL, "User"),
        "is_staff": is_staff,
        "is_verified": is_verified,
        "menu_permissions": menu_permissions,
    }


def require_login(request: Request):
    """Foydalanuvchi tizimga kirmagan bo'lsa login sahifasiga yo'naltiradi.
    Himoyalangan view funksiyalarida chaqiriladi."""
    user_id = request.session.get(SESSION_USER_ID)
    if not user_id:
        return RedirectResponse(
            url="/login?next=" + str(request.url.path),
            status_code=status.HTTP_302_FOUND,
        )
    return None


def set_session(request: Request, user) -> None:
    """Muvaffaqiyatli logindan so'ng session ni to'ldirish."""
    full_name = (
        (getattr(user, "full_name", None) or "").strip()
        or " ".join(
            x
            for x in [
                (getattr(user, "first_name", None) or "").strip(),
                (getattr(user, "second_name", None) or "").strip(),
            ]
            if x
        )
        or (getattr(user, "username", None) or "")
    )
    is_staff = bool(getattr(user, "is_staff", False))
    is_verified = bool(getattr(user, "is_verified", False))
    role_label = "Super Admin" if is_verified else ("Admin" if is_staff else "Foydalanuvchi")
    menu_permissions = normalize_menu_permissions(
        getattr(user, "menu_permissions", None),
        is_staff=is_staff,
        is_verified=is_verified,
    )

    request.session[SESSION_USER_ID] = user.id
    request.session[SESSION_USERNAME] = user.username
    request.session[SESSION_IS_STAFF] = is_staff
    request.session[SESSION_IS_VERIFIED] = is_verified
    request.session[SESSION_FULL_NAME] = full_name
    request.session[SESSION_IMAGE] = getattr(user, "image", "") or ""
    request.session[SESSION_ROLE_LABEL] = role_label
    request.session[SESSION_MENU_PERMISSIONS] = menu_permissions


def clear_session(request: Request) -> None:
    """Logout: session ni to'liq tozalash."""
    request.session.clear()
