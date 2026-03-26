from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.models.library import Library

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

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


@router.get("/", response_class=HTMLResponse)
async def list_libraries(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    # Oxirgi qo'shilganlar yuqorida tursin
    items = db.query(Library).order_by(Library.id.desc()).all()
    return templates.TemplateResponse("libraries/list.html", _ctx(request, items=items, active_menu="libraries", title="Kutubxonalar"))


@router.get("/add", response_class=HTMLResponse)
async def add_library_page(request: Request):
    _guard(request)
    return templates.TemplateResponse("libraries/form.html", _ctx(request, item=None, active_menu="libraries", title="Kutubxona Qo'shish"))


@router.post("/add")
async def add_library_post(
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    number: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    active: bool = Form(False),
    db: Session = Depends(get_db)
):
    user = _guard(request)
    
    # Yangi kutubxona yaratish
    new_lib = Library(
        name=name.strip(),
        address=address.strip(),
        number=number.strip(),
        email=email.strip() if email else None,
        phone=phone.strip() if phone else None,
        active=active,
        user_id=user["id"]
    )
    db.add(new_lib)
    db.commit()
    
    # Qayta ro'yxatga yo'naltirish (Flash notification orqali muvaffaqiyat xabari bilan)
    url = "/libraries?flash_type=success&flash_title=Muvaffaqiyatli&flash_msg=Kutubxona%20qo'shildi"
    return RedirectResponse(url=url, status_code=302)


@router.get("/edit/{item_id}", response_class=HTMLResponse)
async def edit_library_page(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = db.query(Library).filter(Library.id == item_id).first()
    if not item:
        return RedirectResponse(url="/libraries?flash_type=error&flash_msg=Topilmadi", status_code=302)
    return templates.TemplateResponse("libraries/form.html", _ctx(request, item=item, active_menu="libraries", title="Kutubxonani Tahrirlash"))


@router.post("/edit/{item_id}")
async def edit_library_post(
    request: Request,
    item_id: int,
    name: str = Form(...),
    address: str = Form(...),
    number: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    active: bool = Form(False),
    db: Session = Depends(get_db)
):
    _guard(request)
    item = db.query(Library).filter(Library.id == item_id).first()
    if not item:
        return RedirectResponse(url="/libraries?flash_type=error&flash_msg=Topilmadi", status_code=302)
    
    item.name = name.strip()
    item.address = address.strip()
    item.number = number.strip()
    item.email = email.strip() if email else None
    item.phone = phone.strip() if phone else None
    item.active = active
    item.updated_at = datetime.utcnow()
    
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
