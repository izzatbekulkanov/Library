from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import List

from app.core.database import get_db
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.models.library import Library
from app.models.user import User, UserTypeEnum

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# Kutubxona xodimlari roli sifatida qabul qilinadigan turlar.
# Kutubxona Raxbari (lib_head) va Kutubxona xodimi (lib_staff) — ikkalasi ham librariangakirishi mumkin.
LIBRARIAN_USER_TYPES = (UserTypeEnum.lib_staff, UserTypeEnum.lib_head)


def _guard(request: Request, menu_key: str = "libraries"):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if menu_key and not can_access_menu(user, menu_key):
        raise HTTPException(status_code=302, headers={"Location": build_menu_denied_url(user, menu_key)})
    return user

def _ctx(request: Request, **extra):
    qp = request.query_params
    return {
        "request": request, 
        "session_user": get_session_user(request), 
        "flash_type": qp.get("flash_type"),
        "flash_title": qp.get("flash_title"),
        "flash_message": qp.get("flash_msg"),
        **extra
    }


def _eligible_librarians(db: Session) -> list[User]:
    """Faqat 'Kutubxona xodimi' yoki 'Kutubxona Raxbari' turidagi faol foydalanuvchilar."""
    return (
        db.query(User)
        .filter(User.user_type.in_(LIBRARIAN_USER_TYPES))
        .filter(User.is_active == True)  # noqa: E712
        .order_by(User.full_name.asc(), User.username.asc())
        .all()
    )


def _parse_id_list(values) -> list[int]:
    result: list[int] = []
    for raw in values or []:
        if raw is None:
            continue
        try:
            result.append(int(str(raw).strip()))
        except (TypeError, ValueError):
            continue
    # unique, order-preserving
    seen = set()
    unique: list[int] = []
    for value in result:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


@router.get("/", response_class=HTMLResponse)
async def list_libraries(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    items = (
        db.query(Library)
        .options(joinedload(Library.small_librarians))
        .order_by(Library.id.desc())
        .all()
    )

    # Big librarian'lar uchun bitta query bilan map tuzamiz (N+1 ni oldini olish)
    big_ids = {item.big_librarian_id for item in items if item.big_librarian_id}
    big_map: dict[int, User] = {}
    if big_ids:
        for u in db.query(User).filter(User.id.in_(big_ids)).all():
            big_map[u.id] = u

    return templates.TemplateResponse(
        "libraries/list.html",
        _ctx(
            request,
            items=items,
            big_librarian_map=big_map,
            active_menu="libraries",
            title="Kutubxonalar",
        ),
    )


@router.get("/add", response_class=HTMLResponse)
async def add_library_page(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    return templates.TemplateResponse(
        "libraries/form.html",
        _ctx(
            request,
            item=None,
            librarians=_eligible_librarians(db),
            selected_big_id=None,
            selected_small_ids=set(),
            active_menu="libraries",
            title="Kutubxona Qo'shish",
        ),
    )


@router.post("/add")
async def add_library_post(
    request: Request,
    db: Session = Depends(get_db)
):
    user = _guard(request)
    form = await request.form()

    name = (form.get("name") or "").strip()
    address = (form.get("address") or "").strip()
    number = (form.get("number") or "").strip()
    email = (form.get("email") or "").strip()
    phone = (form.get("phone") or "").strip()
    active = bool(form.get("active"))

    big_raw = (form.get("big_librarian_id") or "").strip()
    small_ids = _parse_id_list(form.getlist("small_librarian_ids"))

    big_user = None
    if big_raw:
        try:
            big_id = int(big_raw)
        except ValueError:
            big_id = None
        if big_id:
            big_user = (
                db.query(User)
                .filter(User.id == big_id, User.user_type.in_(LIBRARIAN_USER_TYPES), User.is_active == True)  # noqa: E712
                .first()
            )

    new_lib = Library(
        name=name,
        address=address,
        number=number,
        email=email or None,
        phone=phone or None,
        active=active,
        user_id=user["id"],
        big_librarian_id=big_user.id if big_user else None,
    )

    if small_ids:
        small_users = (
            db.query(User)
            .filter(
                User.id.in_(small_ids),
                User.user_type.in_(LIBRARIAN_USER_TYPES),
                User.is_active == True,  # noqa: E712
            )
            .all()
        )
        # Big librarian bo'lsa, small_librarians ichida takrorlanmasligi kerak
        if big_user:
            small_users = [u for u in small_users if u.id != big_user.id]
        new_lib.small_librarians = small_users

    db.add(new_lib)
    db.commit()
    
    url = "/libraries?flash_type=success&flash_title=Muvaffaqiyatli&flash_msg=Kutubxona%20qo'shildi"
    return RedirectResponse(url=url, status_code=302)


@router.get("/edit/{item_id}", response_class=HTMLResponse)
async def edit_library_page(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = (
        db.query(Library)
        .options(joinedload(Library.small_librarians))
        .filter(Library.id == item_id)
        .first()
    )
    if not item:
        return RedirectResponse(url="/libraries?flash_type=error&flash_msg=Topilmadi", status_code=302)
    selected_small_ids = {u.id for u in (item.small_librarians or [])}
    return templates.TemplateResponse(
        "libraries/form.html",
        _ctx(
            request,
            item=item,
            librarians=_eligible_librarians(db),
            selected_big_id=item.big_librarian_id,
            selected_small_ids=selected_small_ids,
            active_menu="libraries",
            title="Kutubxonani Tahrirlash",
        ),
    )


@router.post("/edit/{item_id}")
async def edit_library_post(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db)
):
    _guard(request)
    item = (
        db.query(Library)
        .options(joinedload(Library.small_librarians))
        .filter(Library.id == item_id)
        .first()
    )
    if not item:
        return RedirectResponse(url="/libraries?flash_type=error&flash_msg=Topilmadi", status_code=302)

    form = await request.form()
    name = (form.get("name") or "").strip()
    address = (form.get("address") or "").strip()
    number = (form.get("number") or "").strip()
    email = (form.get("email") or "").strip()
    phone = (form.get("phone") or "").strip()
    active = bool(form.get("active"))

    big_raw = (form.get("big_librarian_id") or "").strip()
    small_ids = _parse_id_list(form.getlist("small_librarian_ids"))

    big_user = None
    if big_raw:
        try:
            big_id = int(big_raw)
        except ValueError:
            big_id = None
        if big_id:
            big_user = (
                db.query(User)
                .filter(User.id == big_id, User.user_type.in_(LIBRARIAN_USER_TYPES), User.is_active == True)  # noqa: E712
                .first()
            )

    item.name = name
    item.address = address
    item.number = number
    item.email = email or None
    item.phone = phone or None
    item.active = active
    item.big_librarian_id = big_user.id if big_user else None
    item.updated_at = datetime.utcnow()

    if small_ids:
        small_users = (
            db.query(User)
            .filter(
                User.id.in_(small_ids),
                User.user_type.in_(LIBRARIAN_USER_TYPES),
                User.is_active == True,  # noqa: E712
            )
            .all()
        )
        if big_user:
            small_users = [u for u in small_users if u.id != big_user.id]
        item.small_librarians = small_users
    else:
        item.small_librarians = []

    db.commit()
    return RedirectResponse(url="/libraries?flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi", status_code=302)


@router.post("/delete/{item_id}")
async def delete_library_post(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = db.query(Library).filter(Library.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return RedirectResponse(url="/libraries?flash_type=info&flash_msg=Kutubxona%20o'chirildi", status_code=302)
    return RedirectResponse(url="/libraries?flash_type=error&flash_msg=Topilmadi", status_code=302)
