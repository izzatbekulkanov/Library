from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import os
import shutil
import uuid

from app.core.database import get_db
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.models.library import Author

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads/authors"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def _guard(request: Request, menu_key: str = "authors"):
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
async def list_authors(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    items = db.query(Author).order_by(Author.id.desc()).all()
    return templates.TemplateResponse("authors/list.html", _ctx(request, items=items, active_menu="authors", title="Mualliflar"))


@router.get("/add", response_class=HTMLResponse)
async def add_author_page(request: Request):
    _guard(request)
    return templates.TemplateResponse("authors/form.html", _ctx(request, item=None, active_menu="authors", title="Muallif Qo'shish"))


@router.post("/add")
async def add_author_post(
    request: Request,
    name: str = Form(...),
    phone_number: str = Form(""),
    email: str = Form(""),
    author_code: str = Form(""),
    is_active: bool = Form(False),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    user = _guard(request)
    
    # Rasm yuklash (agar bo'lsa)
    image_url = None
    if image and image.filename:
        ext = image.filename.split(".")[-1]
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/static/uploads/authors/{filename}"
        
    new_author = Author(
        name=name.strip(),
        phone_number=phone_number.strip() if phone_number else None,
        email=email.strip() if email else None,
        author_code=author_code.strip() if author_code else None,
        is_active=is_active,
        image=image_url,
        added_by_id=user["id"]
    )
    db.add(new_author)
    db.commit()
    
    return RedirectResponse(
        url="/authors?flash_type=success&flash_title=Muvaffaqiyatli&flash_msg=Muallif%20qo'shildi",
        status_code=302
    )


@router.get("/edit/{item_id}", response_class=HTMLResponse)
async def edit_author_page(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = db.query(Author).filter(Author.id == item_id).first()
    if not item:
        return RedirectResponse(url="/authors?flash_type=error&flash_msg=Topilmadi", status_code=302)
    return templates.TemplateResponse("authors/form.html", _ctx(request, item=item, active_menu="authors", title="Muallifni Tahrirlash"))


@router.post("/edit/{item_id}")
async def edit_author_post(
    request: Request,
    item_id: int,
    name: str = Form(...),
    phone_number: str = Form(""),
    email: str = Form(""),
    author_code: str = Form(""),
    is_active: bool = Form(False),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    _guard(request)
    item = db.query(Author).filter(Author.id == item_id).first()
    if not item:
        return RedirectResponse(url="/authors?flash_type=error&flash_msg=Topilmadi", status_code=302)
    
    item.name = name.strip()
    item.phone_number = phone_number.strip() if phone_number else None
    item.email = email.strip() if email else None
    item.author_code = author_code.strip() if author_code else None
    item.is_active = is_active
    item.updated_at = datetime.utcnow()
    
    # Rasm yuklash (agar yangi bo'lsa)
    if image and image.filename:
        ext = image.filename.split(".")[-1]
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        item.image = f"/static/uploads/authors/{filename}"
        
    db.commit()
    return RedirectResponse(
        url="/authors?flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi",
        status_code=302
    )


@router.post("/delete/{item_id}")
async def delete_author_post(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = db.query(Author).filter(Author.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return RedirectResponse(url="/authors?flash_type=info&flash_msg=Muallif%20o'chirildi", status_code=302)
    return RedirectResponse(url="/authors?flash_type=error&flash_msg=Topilmadi", status_code=302)


# ── AJAX quick-add (kitob formasi uchun) ──────────────────────────────────
from fastapi.responses import JSONResponse
from sqlalchemy import func

@router.post("/api/quick")
async def api_quick_add_author(
    request: Request, 
    name: str = Form(...),
    phone_number: str = Form(None),
    email: str = Form(None),
    author_code: str = Form(None),
    db: Session = Depends(get_db)
):
    user = _guard(request)
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Ism bo'sh bo'lmasin"}, status_code=400)
    existing = db.query(Author).filter(func.lower(Author.name) == name.lower()).first()
    if existing:
        return JSONResponse({"id": existing.id, "name": existing.name})
    
    obj = Author(
        name=name,
        phone_number=phone_number.strip() if phone_number else None,
        email=email.strip() if email else None,
        author_code=author_code.strip() if author_code else None,
        is_active=True, 
        added_by_id=user["id"]
    )
    db.add(obj); db.commit(); db.refresh(obj)
    return JSONResponse({"id": obj.id, "name": obj.name})
