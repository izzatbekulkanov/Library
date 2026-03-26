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
from app.models.library import BookType, BBK

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads/book_types"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def _guard(request: Request, menu_key: str = "book_types"):
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
async def list_book_types(request: Request, tab: str = "book_types", db: Session = Depends(get_db)):
    _guard(request)
    
    # Kitob turlarini olish
    book_types = db.query(BookType).order_by(BookType.id.desc()).all()
    
    # BBK larni olish
    bbks = db.query(BBK).order_by(BBK.id.desc()).all()
    
    return templates.TemplateResponse("book_types/list.html", _ctx(
        request, 
        book_types=book_types, 
        bbks=bbks,
        current_tab=tab,
        active_menu="book_types", 
        title="Kitob Turlari va BBK"
    ))


@router.post("/add")
async def add_book_type_post(
    request: Request,
    name: str = Form(...),
    active: bool = Form(False),
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
        image_url = f"/static/uploads/book_types/{filename}"
        
    new_type = BookType(
        name=name.strip(),
        is_active=active,
        image=image_url,
        user_id=user["id"]
    )
    db.add(new_type)
    db.commit()
    
    return RedirectResponse(
        url="/book_types?tab=book_types&flash_type=success&flash_title=Muvaffaqiyatli&flash_msg=Kitob%20turi%20qo'shildi",
        status_code=302
    )





@router.post("/edit/{item_id}")
async def edit_book_type_post(
    request: Request,
    item_id: int,
    name: str = Form(...),
    active: bool = Form(False),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    _guard(request)
    item = db.query(BookType).filter(BookType.id == item_id).first()
    if not item:
        return RedirectResponse(url="/book_types?tab=book_types&flash_type=error&flash_msg=Topilmadi", status_code=302)
    
    item.name = name.strip()
    item.is_active = active
    item.updated_at = datetime.utcnow()
    
    # Rasm yuklash (agar yangi bo'lsa)
    if image and image.filename:
        ext = image.filename.split(".")[-1]
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        item.image = f"/static/uploads/book_types/{filename}"
        
    db.commit()
    return RedirectResponse(
        url="/book_types?tab=book_types&flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi",
        status_code=302
    )


@router.post("/delete/{item_id}")
async def delete_book_type_post(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = db.query(BookType).filter(BookType.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return RedirectResponse(url="/book_types?tab=book_types&flash_type=info&flash_msg=Kitob%20turi%20o'chirildi", status_code=302)
    return RedirectResponse(url="/book_types?tab=book_types&flash_type=error&flash_msg=Topilmadi", status_code=302)


# ══════════════════════════════════════════════════════════════════════
#  BBK CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/bbk/add")
async def add_bbk_post(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    active: bool = Form(False),
    db: Session = Depends(get_db)
):
    user = _guard(request)
    
    new_bbk = BBK(
        name=name.strip(),
        code=code.strip(),
        is_active=active,
        user_id=user["id"]
    )
    db.add(new_bbk)
    db.commit()
    
    return RedirectResponse(
        url="/book_types?tab=bbk&flash_type=success&flash_title=Muvaffaqiyatli&flash_msg=BBK%20qo'shildi",
        status_code=302
    )


@router.post("/bbk/edit/{item_id}")
async def edit_bbk_post(
    request: Request,
    item_id: int,
    name: str = Form(...),
    code: str = Form(...),
    active: bool = Form(False),
    db: Session = Depends(get_db)
):
    _guard(request)
    item = db.query(BBK).filter(BBK.id == item_id).first()
    if not item:
        return RedirectResponse(url="/book_types?tab=bbk&flash_type=error&flash_msg=Topilmadi", status_code=302)
    
    item.name = name.strip()
    item.code = code.strip()
    item.is_active = active
    item.updated_at = datetime.utcnow()
    
    db.commit()
    return RedirectResponse(
        url="/book_types?tab=bbk&flash_type=success&flash_title=Saqlandi&flash_msg=O'zgarishlar%20saqlandi",
        status_code=302
    )


@router.post("/bbk/delete/{item_id}")
async def delete_bbk_post(request: Request, item_id: int, db: Session = Depends(get_db)):
    _guard(request)
    item = db.query(BBK).filter(BBK.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return RedirectResponse(url="/book_types?tab=bbk&flash_type=info&flash_msg=BBK%20o'chirildi", status_code=302)
    return RedirectResponse(url="/book_types?tab=bbk&flash_type=error&flash_msg=Topilmadi", status_code=302)
