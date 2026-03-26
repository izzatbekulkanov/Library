from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.models.library import Publisher, PublishedCity, PublicationYear

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _guard(request: Request, menu_key: str = "publishers"):
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


# ══════════════════════════════════════════════════════════════
#  MAIN LIST (all 3 models in one page)
# ══════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def list_publishers(request: Request, tab: str = "publishers", db: Session = Depends(get_db)):
    _guard(request)
    publishers    = db.query(Publisher).order_by(Publisher.id.desc()).all()
    cities        = db.query(PublishedCity).order_by(PublishedCity.id.desc()).all()
    years         = db.query(PublicationYear).order_by(PublicationYear.year.desc()).all()

    return templates.TemplateResponse("publishers/list.html", _ctx(
        request,
        publishers=publishers,
        cities=cities,
        years=years,
        current_tab=tab,
        active_menu="publishers",
        title="Nashriyot Ma'lumotlari"
    ))


# ══════════════════════════════════════════════════════════════
#  PUBLISHER CRUD
# ══════════════════════════════════════════════════════════════

@router.post("/add")
async def add_publisher(request: Request, name: str = Form(...), active: bool = Form(False), db: Session = Depends(get_db)):
    user = _guard(request)
    obj = Publisher(name=name.strip(), is_active=active, user_id=user["id"])
    db.add(obj); db.commit()
    return RedirectResponse(url="/publishers?tab=publishers&flash_type=success&flash_title=Qo'shildi&flash_msg=Nashriyot%20qo'shildi", status_code=302)


@router.post("/edit/{item_id}")
async def edit_publisher(request: Request, item_id: int, name: str = Form(...), active: bool = Form(False), db: Session = Depends(get_db)):
    _guard(request)
    obj = db.query(Publisher).filter(Publisher.id == item_id).first()
    if not obj:
        return RedirectResponse(url="/publishers?tab=publishers&flash_type=error&flash_msg=Topilmadi", status_code=302)
    obj.name = name.strip(); obj.is_active = active; obj.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/publishers?tab=publishers&flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi", status_code=302)


@router.post("/delete/{item_id}")
async def delete_publisher(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    obj = db.query(Publisher).filter(Publisher.id == item_id).first()
    if obj: db.delete(obj); db.commit()
        
    return RedirectResponse(url="/publishers?tab=publishers&flash_type=info&flash_msg=O'chirildi", status_code=302)


# ══════════════════════════════════════════════════════════════
#  PUBLISHED CITY CRUD
# ══════════════════════════════════════════════════════════════

@router.post("/city/add")
async def add_city(request: Request, name: str = Form(...), active: bool = Form(False), db: Session = Depends(get_db)):
    user = _guard(request)
    obj = PublishedCity(name=name.strip(), is_active=active, user_id=user["id"])
    db.add(obj); db.commit()
    return RedirectResponse(url="/publishers?tab=cities&flash_type=success&flash_title=Qo'shildi&flash_msg=Shahar%20qo'shildi", status_code=302)


@router.post("/city/edit/{item_id}")
async def edit_city(request: Request, item_id: int, name: str = Form(...), active: bool = Form(False), db: Session = Depends(get_db)):
    _guard(request)
    obj = db.query(PublishedCity).filter(PublishedCity.id == item_id).first()
    if not obj:
        return RedirectResponse(url="/publishers?tab=cities&flash_type=error&flash_msg=Topilmadi", status_code=302)
    obj.name = name.strip(); obj.is_active = active; obj.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/publishers?tab=cities&flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi", status_code=302)


@router.post("/city/delete/{item_id}")
async def delete_city(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    obj = db.query(PublishedCity).filter(PublishedCity.id == item_id).first()
    if obj: db.delete(obj); db.commit()
    return RedirectResponse(url="/publishers?tab=cities&flash_type=info&flash_msg=O'chirildi", status_code=302)


# ══════════════════════════════════════════════════════════════
#  PUBLICATION YEAR CRUD
# ══════════════════════════════════════════════════════════════

@router.post("/year/add")
async def add_year(request: Request, year: int = Form(...), active: bool = Form(False), db: Session = Depends(get_db)):
    user = _guard(request)
    obj = PublicationYear(year=year, is_active=active, user_id=user["id"])
    db.add(obj); db.commit()
    return RedirectResponse(url="/publishers?tab=years&flash_type=success&flash_title=Qo'shildi&flash_msg=Yil%20qo'shildi", status_code=302)


@router.post("/year/edit/{item_id}")
async def edit_year(request: Request, item_id: int, year: int = Form(...), active: bool = Form(False), db: Session = Depends(get_db)):
    _guard(request)
    obj = db.query(PublicationYear).filter(PublicationYear.id == item_id).first()
    if not obj:
        return RedirectResponse(url="/publishers?tab=years&flash_type=error&flash_msg=Topilmadi", status_code=302)
    obj.year = year; obj.is_active = active; obj.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/publishers?tab=years&flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi", status_code=302)


@router.post("/year/delete/{item_id}")
async def delete_year(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    obj = db.query(PublicationYear).filter(PublicationYear.id == item_id).first()
    if obj: db.delete(obj); db.commit()
    return RedirectResponse(url="/publishers?tab=years&flash_type=info&flash_msg=O'chirildi", status_code=302)


# ══════════════════════════════════════════════════════════════
#  AJAX (JSON) – kitob formasi uchun tezkor qo'shish
# ══════════════════════════════════════════════════════════════

from fastapi.responses import JSONResponse
from sqlalchemy import func

@router.post("/api/publisher")
async def api_add_publisher(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = _guard(request)
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Nom bo'sh bo'lmasin"}, status_code=400)
    existing = db.query(Publisher).filter(func.lower(Publisher.name) == name.lower()).first()
    if existing:
        return JSONResponse({"id": existing.id, "name": existing.name})
    obj = Publisher(name=name, is_active=True, user_id=user["id"])
    db.add(obj); db.commit(); db.refresh(obj)
    return JSONResponse({"id": obj.id, "name": obj.name})


@router.post("/api/city")
async def api_add_city(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = _guard(request)
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Nom bo'sh bo'lmasin"}, status_code=400)
    existing = db.query(PublishedCity).filter(func.lower(PublishedCity.name) == name.lower()).first()
    if existing:
        return JSONResponse({"id": existing.id, "name": existing.name})
    obj = PublishedCity(name=name, is_active=True, user_id=user["id"])
    db.add(obj); db.commit(); db.refresh(obj)
    return JSONResponse({"id": obj.id, "name": obj.name})


@router.post("/api/year")
async def api_add_year(request: Request, year: int = Form(...), db: Session = Depends(get_db)):
    user = _guard(request)
    existing = db.query(PublicationYear).filter(PublicationYear.year == year).first()
    if existing:
        return JSONResponse({"id": existing.id, "year": existing.year})
    obj = PublicationYear(year=year, is_active=True, user_id=user["id"])
    db.add(obj); db.commit(); db.refresh(obj)
    return JSONResponse({"id": obj.id, "year": obj.year})
