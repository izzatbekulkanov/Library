from fastapi import APIRouter, Request, Depends, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime
import os, shutil, uuid
import urllib.parse
import re
from collections import defaultdict
from io import BytesIO

from app.core.database import get_db
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.core.system_settings import is_book_delete_blocked
from app.models.library import (
    Book, BookCopy, BookType, BBK, Author,
    Publisher, PublishedCity, PublicationYear, Library
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads/books"
os.makedirs(UPLOAD_DIR, exist_ok=True)

COPY_STATUS_CHOICES = [
    ("not_sended", "Yuborilmagan"),
    ("sent", "Yuborilgan"),
    ("accepted", "Qabul qilingan"),
    ("not_accepted", "Qabul qilinmagan"),
    ("active", "Faol"),
    ("lost", "Yo'qotilgan"),
]
COPY_HAVE_STATUS_CHOICES = [
    ("yes", "Mavjud"),
    ("busy", "Band"),
    ("no", "Mavjud emas"),
]


def _pick_font_paths() -> tuple[str | None, str | None]:
    candidates = [
        ("app/static/fonts/DejaVuSans.ttf", "app/static/fonts/DejaVuSans-Bold.ttf"),
        ("src/assets/fonts/DejaVuSans.ttf", "src/assets/fonts/DejaVuSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for normal, bold in candidates:
        if os.path.exists(normal) and os.path.exists(bold):
            return normal, bold
    return None, None


def _register_pdf_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    normal_path, bold_path = _pick_font_paths()
    if normal_path and bold_path:
        try:
            pdfmetrics.registerFont(TTFont("AppNormal", normal_path))
            pdfmetrics.registerFont(TTFont("AppBold", bold_path))
            return "AppNormal", "AppBold"
        except Exception:
            pass
    return "Helvetica", "Helvetica-Bold"


def _format_inventory_ranges(invs: list[str]) -> str:
    if not invs:
        return ""
    prefixes = {inv.rsplit("/", 1)[0] for inv in invs if "/" in inv}
    if len(prefixes) != 1:
        return ", ".join(sorted(invs))
    prefix = list(prefixes)[0] + "/" if prefixes else ""
    try:
        numbers = sorted([int(inv.rsplit("/", 1)[1]) for inv in invs if "/" in inv])
    except ValueError:
        return ", ".join(sorted(invs))
    if not numbers:
        return ""
    ranges: list[str] = []
    start = current = numbers[0]
    for num in numbers[1:]:
        if num == current + 1:
            current = num
        else:
            ranges.append(str(start) if start == current else f"{start}-{current}")
            start = current = num
    ranges.append(str(start) if start == current else f"{start}-{current}")
    return prefix + ", ".join(ranges)


def _draw_justified_block(
    p,
    text: str,
    x: float,
    y: float,
    width: float,
    font_name: str,
    font_size: float,
    line_height: float,
    max_lines: int,
    first_line_indent: float = 0.0,
) -> float:
    words = [w for w in (text or "").split() if w]
    if not words:
        return y

    lines: list[list[str]] = []
    line: list[str] = []
    for word in words:
        probe = line + [word]
        probe_text = " ".join(probe)
        indent = first_line_indent if not lines else 0.0
        if p.stringWidth(probe_text, font_name, font_size) <= (width - indent):
            line = probe
        else:
            if line:
                lines.append(line)
                if len(lines) >= max_lines:
                    break
            line = [word]
    if line and len(lines) < max_lines:
        lines.append(line)

    for idx, items in enumerate(lines):
        last = idx == len(lines) - 1
        indent = first_line_indent if idx == 0 else 0.0
        line_x = x + indent
        available = width - indent
        if len(items) == 1 or last:
            p.setFont(font_name, font_size)
            p.drawString(line_x, y, " ".join(items))
            y -= line_height
            continue

        words_width = sum(p.stringWidth(w, font_name, font_size) for w in items)
        gaps = len(items) - 1
        gap_width = (available - words_width) / gaps if gaps else 0
        current_x = line_x
        p.setFont(font_name, font_size)
        for pos, w in enumerate(items):
            p.drawString(current_x, y, w)
            current_x += p.stringWidth(w, font_name, font_size)
            if pos < gaps:
                current_x += gap_width
        y -= line_height
    return y


def _parse_selected_copy_ids(copy_ids: Optional[str]) -> set[int]:
    if not copy_ids:
        return set()
    selected: set[int] = set()
    for chunk in re.split(r"[,\s]+", copy_ids.strip()):
        if not chunk:
            continue
        try:
            value = int(chunk)
            if value > 0:
                selected.add(value)
        except ValueError:
            continue
    return selected


def _guard(request: Request, menu_key: str = "books"):
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
        **extra,
    }


def _save_file(upload: UploadFile, sub: str) -> str | None:
    if not upload or not upload.filename:
        return None
    ext  = os.path.splitext(upload.filename)[-1]
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, sub, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return f"/static/uploads/books/{sub}/{name}"


# ══════════════════════════════════════════════════
#  LIST
# ══════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def list_books(
    request: Request,
    page: int = 1,
    per_page: int = 50,
    q: Optional[str] = None,
    type_id: Optional[str] = None,
    author_id: Optional[str] = None,
    bbk_id: Optional[str] = None,
    language: Optional[str] = None,
    db: Session = Depends(get_db)
):
    _guard(request)
    
    try: type_id = int(type_id) if type_id else None
    except ValueError: type_id = None
    
    try: author_id = int(author_id) if author_id else None
    except ValueError: author_id = None
    
    try: bbk_id = int(bbk_id) if bbk_id else None
    except ValueError: bbk_id = None

    per_page = 50
    query = db.query(Book)
    if q:
        query = query.filter(Book.title.ilike(f"%{q}%"))
    if type_id:
        query = query.filter(Book.book_type_id == type_id)
    if bbk_id:
        query = query.filter(Book.bbk_id == bbk_id)
    if author_id:
        query = query.filter(Book.authors.any(Author.id == author_id))
    if language:
        query = query.filter(Book.language == language)

    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    if page < 1: page = 1
    if total_pages and page > total_pages:
        page = total_pages
    
    books = (
        query.order_by(Book.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    
    from app.models.library import BookType, BBK, Author
    types = db.query(BookType).order_by(BookType.name).all()
    bbks = db.query(BBK).order_by(BBK.name).all()
    authors = db.query(Author).order_by(Author.name).all()

    langs_raw = db.query(Book.language).filter(Book.language.isnot(None)).distinct().all()
    languages = sorted([str(row[0]).lower() for row in langs_raw if str(row[0]).strip()])
    
    LANGUAGE_OPTIONS = [
        ("uz", "O'zbek (lotin)"), ("oz", "O'zbek (kirill)"), ("ru", "Rus"),
        ("en", "Ingliz"), ("tr", "Turk"), ("fr", "Fransuz"), ("de", "Nemis"),
        ("zh", "Xitoy"), ("ar", "Arab"), ("kk", "Qozoq"), ("ky", "Qirg'iz")
    ]
    LANGUAGE_LABELS = dict(LANGUAGE_OPTIONS)

    query_parts: list[str] = []
    if q:
        query_parts.append(f"q={urllib.parse.quote(str(q))}")
    if type_id:
        query_parts.append(f"type_id={int(type_id)}")
    if author_id:
        query_parts.append(f"author_id={int(author_id)}")
    if bbk_id:
        query_parts.append(f"bbk_id={int(bbk_id)}")
    if language:
        query_parts.append(f"language={urllib.parse.quote(str(language))}")
    page_url_base = f"?{'&'.join(query_parts)}&page=" if query_parts else "?page="

    return templates.TemplateResponse("books/list.html", _ctx(
        request,
        books=books,
        page=page,
        total_pages=total_pages,
        total_items=total,
        per_page=per_page,
        q=q or "",
        type_id=type_id or "",
        author_id=author_id or "",
        bbk_id=bbk_id or "",
        language=language or "",
        types=types,
        bbks=bbks,
        authors=authors,
        languages=languages,
        language_labels=LANGUAGE_LABELS,
        page_url_base=page_url_base,
        active_menu="books",
        title="Kitoblar"
    ))


# ══════════════════════════════════════════════════
#  DELETE BOOK
# ══════════════════════════════════════════════════
@router.get("/delete/{book_id}")
async def delete_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    if is_book_delete_blocked():
        return RedirectResponse(
            url=f"/books?flash_type=warning&flash_msg={urllib.parse.quote('Kitoblarni o‘chirish tizim sozlamalarida vaqtincha taqiqlangan.')}",
            status_code=303,
        )
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Kitob topilmadi.')}",
            status_code=303
        )

    has_copies = (
        db.query(BookCopy.id)
        .filter(BookCopy.original_book_id == book_id)
        .first()
        is not None
    )
    if has_copies:
        return RedirectResponse(
            url=f"/books?flash_type=warning&flash_msg={urllib.parse.quote('Kitobda mavjud nusxalar borligi sababli uni o`chirib bo`lmaydi. Avval nusxalarni o`chiring.')}",
            status_code=303
        )

    try:
        db.execute(text("DELETE FROM book_authors WHERE book_id = :b_id"), {"b_id": book_id})
        db.delete(book)
        db.commit()
        return RedirectResponse(
            url=f"/books?flash_type=success&flash_msg={urllib.parse.quote('Kitob muvaffaqiyatli o`chirildi.')}",
            status_code=303
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Xatolik yuz berdi: ' + str(e))}",
            status_code=303
        )


# ══════════════════════════════════════════════════
#  EDIT BOOK – GET (form page)
# ══════════════════════════════════════════════════
@router.get("/edit/{book_id}", response_class=HTMLResponse)
async def edit_book_page(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Kitob topilmadi.')}",
            status_code=303
        )

    types = db.query(BookType).order_by(BookType.name).all()
    bbks = db.query(BBK).order_by(BBK.name).all()
    publishers = db.query(Publisher).order_by(Publisher.name).all()
    cities = db.query(PublishedCity).order_by(PublishedCity.name).all()
    years = db.query(PublicationYear).order_by(PublicationYear.year.desc()).all()
    authors = db.query(Author).order_by(Author.name).all()

    languages = [
         ("uz", "O'zbek (lotin)"), ("oz", "O'zbek (kiril)"), ("ru", "Rus tili"), 
         ("en", "Ingliz tili"),    ("tr", "Turk tili"),    ("de", "Nemis tili"), 
         ("fr", "Fransuz tili"),   ("kk", "Qozoq tili"),   ("ky", "Qirg'iz tili"), 
         ("other", "Boshqa")
    ]
    language_labels = dict(languages)

    return templates.TemplateResponse("books/edit.html", _ctx(
        request,
        book=book,
        book_types=types,
        bbks=bbks,
        publishers=publishers,
        cities=cities,
        years=years,
        authors=authors,
        languages=languages,
        language_labels=language_labels,
        active_menu="books",
        title=f"Tahrirlash: {book.title}"
    ))

# ══════════════════════════════════════════════════
#  EDIT BOOK – POST (save)
# ══════════════════════════════════════════════════
@router.post("/edit/{book_id}")
async def edit_book_post(
    book_id: int,
    request: Request,
    title: str = Form(...),
    language: str = Form('uz'),
    pages: Optional[int] = Form(None),
    isbn: Optional[str] = Form(None),
    annotation: Optional[str] = Form(None),
    adad: Optional[int] = Form(0),
    price: Optional[float] = Form(0),
    book_type_id: Optional[int] = Form(None),
    bbk_id: Optional[int] = Form(None),
    author_ids: list[int] = Form(default=[]),
    publisher_id: Optional[int] = Form(None),
    published_city_id: Optional[int] = Form(None),
    publication_year_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user = _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(url="/books", status_code=303)

    from app.models.library import Author
    
    # Update files only if new ones are provided
    if image and image.filename:
        book.image = _save_file(image, "images")
    if file and file.filename:
        book.file = _save_file(file, "files")

    book.title = title.strip()
    book.language = language
    book.pages = pages
    book.isbn = isbn.strip() if isbn else None
    book.annotation = annotation
    book.adad = adad or 0
    book.price = price or 0
    book.book_type_id = book_type_id
    book.bbk_id = bbk_id
    book.publisher_id = publisher_id
    book.published_city_id = published_city_id
    book.publication_year_id = publication_year_id

    # Update authors
    book.authors = []
    if author_ids:
        found_authors = db.query(Author).filter(Author.id.in_(author_ids)).all()
        book.authors = found_authors

    try:
        db.commit()
        return RedirectResponse(
            url=f"/books?flash_type=success&flash_msg={urllib.parse.quote('Kitob muvaffaqiyatli saqlandi.')}",
            status_code=303
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=f"/books/edit/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Xatolik: ' + str(e))}",
            status_code=303
        )

# ══════════════════════════════════════════════════
#  ADD – GET (form page)
# ══════════════════════════════════════════════════

@router.get("/add", response_class=HTMLResponse)
async def add_book_page(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    return templates.TemplateResponse("books/add.html", _ctx(
        request,
        book_types     = db.query(BookType).filter(BookType.is_active == True).all(),
        bbks           = db.query(BBK).filter(BBK.is_active == True).all(),
        authors        = db.query(Author).filter(Author.is_active == True).all(),
        publishers     = db.query(Publisher).filter(Publisher.is_active == True).all(),
        cities         = db.query(PublishedCity).filter(PublishedCity.is_active == True).all(),
        years          = db.query(PublicationYear).filter(PublicationYear.is_active == True).order_by(PublicationYear.year.desc()).all(),
        languages      = [
            ('uz', "O'zbek (lotin)"), ('oz', "O'zbek (kirill)"),
            ('ru', "Rus"), ('en', "Ingliz"), ('tr', "Turk"),
            ('fr', "Fransuz"), ('de', "Nemis"), ('zh', "Xitoy"),
            ('ar', "Arab"), ('kk', "Qozoq"), ('ky', "Qirg'iz"),
        ],
        active_menu="books",
        title="Yangi Kitob Qo'shish"
    ))


# ══════════════════════════════════════════════════
#  ADD – POST (save)
# ══════════════════════════════════════════════════

@router.post("/add")
async def add_book(
    request: Request,
    # --- Asosiy maydonlar ---
    title: str          = Form(...),
    language: str       = Form('uz'),
    pages: Optional[int]= Form(None),
    isbn: Optional[str] = Form(None),
    annotation: Optional[str] = Form(None),
    adad: Optional[int] = Form(0),
    price: Optional[float] = Form(0),
    # --- FK ---
    book_type_id: Optional[int]        = Form(None),
    bbk_id: Optional[int]              = Form(None),
    author_ids: list[int]              = Form(default=[]),
    publisher_id: Optional[int]        = Form(None),
    published_city_id: Optional[int]   = Form(None),
    publication_year_id: Optional[int] = Form(None),
    # --- Inventar ---
    inventory_prefix: Optional[str] = Form(None),
    copy_count: int                  = Form(0),
    # --- Fayllar ---
    image: Optional[UploadFile] = File(None),
    file:  Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    user = _guard(request)

    image_path = _save_file(image, "images") if image and image.filename else None
    file_path  = _save_file(file,  "files")  if file  and file.filename  else None

    book = Book(
        title              = title.strip(),
        language           = language,
        pages              = pages,
        isbn               = isbn.strip() if isbn else None,
        annotation         = annotation,
        adad               = adad or 0,
        price              = price or 0,
        image              = image_path,
        file               = file_path,
        book_type_id       = book_type_id,
        bbk_id             = bbk_id,
        publisher_id       = publisher_id,
        published_city_id  = published_city_id,
        publication_year_id= publication_year_id,
        added_by_id        = user["id"],
        total_copies       = copy_count,
        total_inventory    = inventory_prefix or '',
    )

    # M2M authors
    if author_ids:
        book.authors = db.query(Author).filter(Author.id.in_(author_ids)).all()

    db.add(book)
    db.flush()   # book.id olinadi

    # Nusxalar yaratish
    prefix = (inventory_prefix or '').strip()
    for i in range(1, copy_count + 1):
        inv_num = f"{prefix}/{i}" if prefix else str(i)
        copy = BookCopy(
            original_book_id = book.id,
            inventory_number = inv_num,
            is_print         = True,
            status           = 'not_sended',
            have_status      = 'yes',
        )
        db.add(copy)

    db.commit()

    return RedirectResponse(
        url=f"/books?flash_type=success&flash_title=Kitob+qo%27shildi&flash_msg={copy_count}+ta+nusxa+yaratildi",
        status_code=302
    )

# ══════════════════════════════════════════════════
#  VIEW BOOK (Batafsil)
# ══════════════════════════════════════════════════
@router.get("/{book_id}", response_class=HTMLResponse)
async def view_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Kitob topilmadi.')}",
            status_code=303
        )
    libraries = db.query(Library).order_by(Library.name).all()
    return templates.TemplateResponse("books/view.html", _ctx(
        request,
        book=book,
        libraries=libraries,
        copy_statuses=COPY_STATUS_CHOICES,
        copy_have_statuses=COPY_HAVE_STATUS_CHOICES,
        active_menu="books"
    ))


# ══════════════════════════════════════════════════
#  ADD BOOK COPIES (from detail page)
# ══════════════════════════════════════════════════
@router.get("/{book_id}/print/id-card/select", response_class=HTMLResponse)
@router.get("/{book_id}/print/id-card/select/", response_class=HTMLResponse)
@router.get("/print/id-card/{book_id}/select", response_class=HTMLResponse)
@router.get("/print/id-card/{book_id}/select/", response_class=HTMLResponse)
async def select_book_id_cards_for_print(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Kitob topilmadi.")
        return RedirectResponse(url=f"/books?flash_type=error&flash_msg={msg}", status_code=303)

    copies = sorted(book.copies or [], key=lambda x: (x.inventory_number or "", x.id or 0))
    return templates.TemplateResponse(
        "books/print_select.html",
        _ctx(
            request,
            book=book,
            copies=copies,
            print_mode="id_card",
            print_title="ID karta",
            print_endpoint=f"/books/print/id-card/{book.id}",
            active_menu="books",
        ),
    )


@router.get("/{book_id}/print/qr-codes/select", response_class=HTMLResponse)
@router.get("/{book_id}/print/qr-codes/select/", response_class=HTMLResponse)
@router.get("/{book_id}/print-qr-codes/select", response_class=HTMLResponse)
@router.get("/{book_id}/print-qr-codes/select/", response_class=HTMLResponse)
@router.get("/print/qr-codes/{book_id}/select", response_class=HTMLResponse)
@router.get("/print/qr-codes/{book_id}/select/", response_class=HTMLResponse)
async def select_book_qr_for_print(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Kitob topilmadi.")
        return RedirectResponse(url=f"/books?flash_type=error&flash_msg={msg}", status_code=303)

    copies = sorted(book.copies or [], key=lambda x: (x.inventory_number or "", x.id or 0))
    return templates.TemplateResponse(
        "books/print_select.html",
        _ctx(
            request,
            book=book,
            copies=copies,
            print_mode="qr_code",
            print_title="QR kod",
            print_endpoint=f"/books/print/qr-codes/{book.id}",
            active_menu="books",
        ),
    )


@router.get("/{book_id}/print/id-card")
@router.get("/{book_id}/print/id-card/")
@router.get("/{book_id}/print-id-card")
@router.get("/{book_id}/print-id-card/")
@router.get("/print/id-card/{book_id}")
@router.get("/print/id-card/{book_id}/")
async def print_book_id_card(
    book_id: int,
    request: Request,
    copy_ids: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _guard(request)
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.units import cm
        from reportlab.lib.colors import black
    except Exception:
        msg = urllib.parse.quote("ID karta chop etish uchun reportlab o'rnatilmagan.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Kitob topilmadi.")
        return RedirectResponse(url=f"/books?flash_type=error&flash_msg={msg}", status_code=303)

    copies = sorted(book.copies or [], key=lambda x: (x.inventory_number or "", x.id or 0))
    selected_ids = _parse_selected_copy_ids(copy_ids)
    if selected_ids:
        copies = [copy for copy in copies if copy.id in selected_ids]
    if not copies:
        msg = urllib.parse.quote("ID karta chop etish uchun tanlangan nusxalar topilmadi.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=warning&flash_msg={msg}", status_code=303)

    normal_font, bold_font = _register_pdf_fonts()
    output = BytesIO()
    p = canvas.Canvas(output, pagesize=landscape(A4))
    width, height = landscape(A4)

    card_width = 12.5 * cm
    card_height = 7.5 * cm
    x_margin = 2 * cm
    y_margin = 2 * cm
    x_spacing = 1.0 * cm
    y_spacing = 1.0 * cm
    cards_per_row = 2
    cards_per_col = 2
    cards_per_page = cards_per_row * cards_per_col

    libraries: defaultdict[str, list[str]] = defaultdict(list)
    for copy in copies:
        lib_name = copy.library.name if copy.library else "Noma'lum kutubxona"
        inv_num = (copy.inventory_number or "").strip()
        if inv_num:
            libraries[lib_name].append(inv_num)
    library_text = ", ".join(
        f"{lib} {_format_inventory_ranges(invs)}".strip()
        for lib, invs in sorted(libraries.items(), key=lambda x: x[0])
    )

    first_author = book.authors[0] if (book.authors or []) else None
    bbk_code = book.bbk.code if book.bbk else "---"
    author_code = (first_author.author_code if first_author and first_author.author_code else "---")
    authors = (book.authors or [])[:2]
    authors_text = ", ".join(a.name for a in authors) if authors else "---"
    book_type_name = book.book_type.name if book.book_type else "Noma'lum"
    publisher = book.publisher.name if book.publisher else "Noma'lum nashriyot"
    published_city = book.published_city.name if book.published_city else "Noma'lum shahar"
    publication_year = book.publication_year.year if book.publication_year else "Noma'lum"
    pages = book.pages if book.pages else "---"
    isbn = book.isbn if book.isbn else "---"
    adad = int(book.adad or 0)
    try:
        price_value = float(book.price or 0)
    except Exception:
        price_value = 0.0
    price_text = f"{price_value:,.2f}".replace(",", " ")

    main_desc = (
        f"{book.title} : {book_type_name} / {authors_text}. - "
        f"{published_city}: {publisher}, {publication_year}. - {pages} b. - "
        f"ISBN {isbn}. {price_text} so'm, {adad} adad."
    )

    for i, _copy in enumerate(copies):
        local_index = i % cards_per_page
        row = local_index // cards_per_row
        col = local_index % cards_per_row

        x = x_margin + col * (card_width + x_spacing)
        y = height - y_margin - (row + 1) * (card_height + y_spacing) + y_spacing - 0.5 * cm

        p.setLineWidth(0.5)
        p.setStrokeColor(black)
        p.rect(x, y, card_width, card_height)

        p.setFont(bold_font, 10)
        p.drawString(x + 0.3 * cm, y + card_height - 1.0 * cm, f"BBK: {bbk_code}")
        p.drawString(x + 0.3 * cm, y + card_height - 1.6 * cm, f"Muallif kodi: {author_code}")
        p.drawString(x + 0.3 * cm, y + card_height - 2.2 * cm, authors_text)

        content_x = x + 0.3 * cm
        content_w = card_width - 0.6 * cm
        content_y = y + card_height - 3.0 * cm

        content_y = _draw_justified_block(
            p=p,
            text=book.title,
            x=content_x,
            y=content_y,
            width=content_w,
            font_name=bold_font,
            font_size=11,
            line_height=0.44 * cm,
            max_lines=3,
            first_line_indent=0.35 * cm,
        )

        bibliographic_text = main_desc.replace(book.title, "", 1).lstrip(" :")
        _draw_justified_block(
            p=p,
            text=bibliographic_text,
            x=content_x,
            y=content_y,
            width=content_w,
            font_name=normal_font,
            font_size=9.5,
            line_height=0.42 * cm,
            max_lines=4,
            first_line_indent=0.35 * cm,
        )

        _draw_justified_block(
            p=p,
            text=library_text,
            x=content_x,
            y=y + 1.0 * cm,
            width=content_w,
            font_name=normal_font,
            font_size=9,
            line_height=0.40 * cm,
            max_lines=2,
        )

        if (i + 1) % cards_per_page == 0 and (i + 1) < len(copies):
            p.showPage()

    p.save()
    pdf_bytes = output.getvalue()
    output.close()

    now = datetime.utcnow()
    for copy in copies:
        copy.id_card_printed = True
        copy.id_card_printed_at = now
        copy.is_print = True
    db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="book_{book.id}_id_cards.pdf"'},
    )


@router.get("/{book_id}/copies/{copy_id}/print/id-card")
@router.get("/{book_id}/copies/{copy_id}/print/id-card/")
@router.get("/{book_id}/copies/{copy_id}/print-id-card")
@router.get("/{book_id}/copies/{copy_id}/print-id-card/")
async def print_single_copy_id_card(book_id: int, copy_id: int, request: Request, db: Session = Depends(get_db)):
    return await print_book_id_card(
        book_id=book_id,
        request=request,
        copy_ids=str(copy_id),
        db=db,
    )


@router.get("/{book_id}/print/qr-codes")
@router.get("/{book_id}/print/qr-codes/")
@router.get("/{book_id}/print-qr-codes")
@router.get("/{book_id}/print-qr-codes/")
@router.get("/print/qr-codes/{book_id}")
@router.get("/print/qr-codes/{book_id}/")
async def print_book_qr_codes(
    book_id: int,
    request: Request,
    copy_ids: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _guard(request)
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
    except Exception:
        msg = urllib.parse.quote("QR chop etish uchun reportlab o'rnatilmagan.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Kitob topilmadi.")
        return RedirectResponse(url=f"/books?flash_type=error&flash_msg={msg}", status_code=303)

    copies = sorted(book.copies or [], key=lambda x: (x.inventory_number or "", x.id or 0))
    selected_ids = _parse_selected_copy_ids(copy_ids)
    if selected_ids:
        copies = [copy for copy in copies if copy.id in selected_ids]
    if not copies:
        msg = urllib.parse.quote("QR chop etish uchun tanlangan nusxalar topilmadi.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=warning&flash_msg={msg}", status_code=303)

    normal_font, bold_font = _register_pdf_fonts()
    output = BytesIO()
    p = canvas.Canvas(output, pagesize=A4)
    width, height = A4

    label_w = 6.0 * cm
    label_h = 6.8 * cm
    x_margin = 1.2 * cm
    y_margin = 1.2 * cm
    x_spacing = 0.6 * cm
    y_spacing = 0.6 * cm
    cols = 3
    rows = 4
    labels_per_page = cols * rows

    base_url = str(request.base_url).rstrip("/")
    for i, copy in enumerate(copies):
        local = i % labels_per_page
        row = local // cols
        col = local % cols

        x = x_margin + col * (label_w + x_spacing)
        y = height - y_margin - (row + 1) * (label_h + y_spacing) + y_spacing

        p.setLineWidth(0.5)
        p.rect(x, y, label_w, label_h)

        inv = (copy.inventory_number or f"COPY-{copy.id}").strip()
        qr_data = f"{base_url}/books/{book.id}?copy_id={copy.id}&inv={urllib.parse.quote(inv)}"
        qr_code = qr.QrCodeWidget(qr_data)
        b = qr_code.getBounds()
        qr_w = b[2] - b[0]
        qr_h = b[3] - b[1]
        qr_size = 4.2 * cm
        d = Drawing(qr_size, qr_size, transform=[qr_size / qr_w, 0, 0, qr_size / qr_h, 0, 0])
        d.add(qr_code)
        renderPDF.draw(d, p, x + (label_w - qr_size) / 2, y + 1.7 * cm)

        p.setFont(bold_font, 9)
        p.drawCentredString(x + label_w / 2, y + 1.2 * cm, inv[:45])
        p.setFont(normal_font, 8)
        p.drawCentredString(x + label_w / 2, y + 0.8 * cm, f"Book #{book.id} | Copy #{copy.id}")

        if (i + 1) % labels_per_page == 0 and (i + 1) < len(copies):
            p.showPage()

    p.save()
    pdf_bytes = output.getvalue()
    output.close()

    now = datetime.utcnow()
    for copy in copies:
        copy.qr_printed = True
        copy.qr_printed_at = now
    db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="book_{book.id}_qr_codes.pdf"'},
    )


@router.get("/{book_id}/copies/{copy_id}/print/qr")
@router.get("/{book_id}/copies/{copy_id}/print/qr/")
@router.get("/{book_id}/copies/{copy_id}/print-qr")
@router.get("/{book_id}/copies/{copy_id}/print-qr/")
async def print_single_copy_qr(book_id: int, copy_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
    except Exception:
        msg = urllib.parse.quote("QR chop etish uchun reportlab o'rnatilmagan.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    copy = (
        db.query(BookCopy)
        .filter(BookCopy.id == copy_id, BookCopy.original_book_id == book_id)
        .first()
    )
    if not copy:
        msg = urllib.parse.quote("Nusxa topilmadi.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    output = BytesIO()
    page_w = 8.0 * cm
    page_h = 10.0 * cm
    p = canvas.Canvas(output, pagesize=(page_w, page_h))
    normal_font, bold_font = _register_pdf_fonts()
    inv = (copy.inventory_number or f"COPY-{copy.id}").strip()
    base_url = str(request.base_url).rstrip("/")
    qr_data = f"{base_url}/books/{book_id}?copy_id={copy.id}&inv={urllib.parse.quote(inv)}"

    qr_code = qr.QrCodeWidget(qr_data)
    b = qr_code.getBounds()
    qr_w = b[2] - b[0]
    qr_h = b[3] - b[1]
    qr_size = 5.0 * cm
    d = Drawing(qr_size, qr_size, transform=[qr_size / qr_w, 0, 0, qr_size / qr_h, 0, 0])
    d.add(qr_code)

    p.setLineWidth(0.5)
    p.rect(0.5 * cm, 0.5 * cm, page_w - 1.0 * cm, page_h - 1.0 * cm)
    renderPDF.draw(d, p, (page_w - qr_size) / 2, 3.0 * cm)
    p.setFont(bold_font, 11)
    p.drawCentredString(page_w / 2, 2.2 * cm, inv[:42])
    p.setFont(normal_font, 8)
    p.drawCentredString(page_w / 2, 1.7 * cm, f"Book #{book_id} | Copy #{copy.id}")
    p.showPage()
    p.save()

    copy.qr_printed = True
    copy.qr_printed_at = datetime.utcnow()
    db.commit()

    pdf_bytes = output.getvalue()
    output.close()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="book_{book_id}_copy_{copy.id}_qr.pdf"'},
    )


@router.post("/{book_id}/print/id-card/reset-status")
@router.post("/{book_id}/print/id-card/reset-status/")
@router.post("/print/id-card/{book_id}/reset-status")
@router.post("/print/id-card/{book_id}/reset-status/")
async def reset_book_id_card_print_status(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Kitob topilmadi.")
        return RedirectResponse(url=f"/books?flash_type=error&flash_msg={msg}", status_code=303)

    copies = list(book.copies or [])
    if not copies:
        msg = urllib.parse.quote("Statusni tozalash uchun nusxalar topilmadi.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=warning&flash_msg={msg}", status_code=303)

    for copy in copies:
        copy.id_card_printed = False
        copy.id_card_printed_at = None
        copy.is_print = False
    db.commit()

    msg = urllib.parse.quote(f"ID karta chop etish statusi {len(copies)} ta nusxa uchun tozalandi.")
    return RedirectResponse(url=f"/books/{book_id}?flash_type=success&flash_msg={msg}", status_code=303)


@router.post("/{book_id}/print/qr-codes/reset-status")
@router.post("/{book_id}/print/qr-codes/reset-status/")
@router.post("/{book_id}/print-qr-codes/reset-status")
@router.post("/{book_id}/print-qr-codes/reset-status/")
@router.post("/print/qr-codes/{book_id}/reset-status")
@router.post("/print/qr-codes/{book_id}/reset-status/")
async def reset_book_qr_print_status(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Kitob topilmadi.")
        return RedirectResponse(url=f"/books?flash_type=error&flash_msg={msg}", status_code=303)

    copies = list(book.copies or [])
    if not copies:
        msg = urllib.parse.quote("Statusni tozalash uchun nusxalar topilmadi.")
        return RedirectResponse(url=f"/books/{book_id}?flash_type=warning&flash_msg={msg}", status_code=303)

    for copy in copies:
        copy.qr_printed = False
        copy.qr_printed_at = None
    db.commit()

    msg = urllib.parse.quote(f"QR chop etish statusi {len(copies)} ta nusxa uchun tozalandi.")
    return RedirectResponse(url=f"/books/{book_id}?flash_type=success&flash_msg={msg}", status_code=303)


@router.get("/copies/inventory/check")
@router.get("/copies/inventory/check/")
async def check_inventory_number(
    request: Request,
    inventory_number: str,
    exclude_copy_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    _guard(request)
    inv = (inventory_number or "").strip()
    if not inv:
        return JSONResponse({"exists": False, "inventory_number": "", "message": "Inventar raqami kiritilmagan."})

    query = db.query(BookCopy).filter(BookCopy.inventory_number == inv)
    if exclude_copy_id:
        query = query.filter(BookCopy.id != exclude_copy_id)
    found = query.first()
    return JSONResponse(
        {
            "exists": bool(found),
            "inventory_number": inv,
            "copy_id": found.id if found else None,
            "message": "Bu inventar raqami band." if found else "Inventar raqami bo'sh.",
        }
    )


# accept both with and without trailing slash
@router.post("/{book_id}/copies/add")
@router.post("/{book_id}/copies/add/")
async def add_book_copies(
    book_id: int,
    request: Request,
    inventory_prefix: str = Form(...),
    copy_count: int = Form(...),
    db: Session = Depends(get_db),
):
    _guard(request)

    prefix = (inventory_prefix or "").strip()
    if not prefix:
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Inventar prefiksini kiriting.')}",
            status_code=303,
        )
    if copy_count is None or copy_count < 1:
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Nusxa soni 1 dan katta bo‘lishi kerak.')}",
            status_code=303,
        )

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Kitob topilmadi.')}",
            status_code=303,
        )

    # Determine next suffix number by scanning existing copies for this book & prefix.
    # Pattern: PREFIX/123
    pat = re.compile(rf"^{re.escape(prefix)}/(\\d+)$")
    max_n = 0
    for c in (book.copies or []):
        if not c.inventory_number:
            continue
        m = pat.match(c.inventory_number.strip())
        if m:
            try:
                max_n = max(max_n, int(m.group(1)))
            except ValueError:
                pass

    start_n = max_n + 1
    inv_numbers = [f"{prefix}/{i}" for i in range(start_n, start_n + int(copy_count))]

    # Duplicate check across ALL copies in DB
    exists = (
        db.query(BookCopy.inventory_number)
        .filter(BookCopy.inventory_number.in_(inv_numbers))
        .limit(1)
        .first()
    )
    if exists:
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Bazada bunday inventar raqami mavjud: ' + str(exists[0]))}",
            status_code=303,
        )

    try:
        for inv in inv_numbers:
            db.add(
                BookCopy(
                    original_book_id=book.id,
                    inventory_number=inv,
                    is_print=True,
                    status="not_sended",
                    have_status="yes",
                )
            )

        # Keep totals consistent
        book.total_copies = (book.total_copies or 0) + int(copy_count)
        if not (book.total_inventory or "").strip():
            book.total_inventory = prefix

        db.commit()
        msg = urllib.parse.quote(f"{copy_count} ta nusxa qo'shildi.")
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=success&flash_msg={msg}",
            status_code=303,
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Xatolik: ' + str(e))}",
            status_code=303,
        )


# ══════════════════════════════════════════════════
#  DELETE BOOK COPY (from detail page)
# ══════════════════════════════════════════════════
@router.post("/{book_id}/copies/edit/{copy_id}")
@router.post("/{book_id}/copies/edit/{copy_id}/")
async def edit_book_copy(
    book_id: int,
    copy_id: int,
    request: Request,
    inventory_number: str = Form(...),
    status: str = Form("not_sended"),
    have_status: str = Form("yes"),
    library_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _guard(request)

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Kitob topilmadi.')}",
            status_code=303,
        )

    copy = (
        db.query(BookCopy)
        .filter(BookCopy.id == copy_id, BookCopy.original_book_id == book_id)
        .first()
    )
    if not copy:
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Nusxa topilmadi.')}",
            status_code=303,
        )

    inv = (inventory_number or "").strip()
    if not inv:
        msg = urllib.parse.quote("Inventar raqami bo'sh bo'lmasligi kerak.")
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={msg}",
            status_code=303,
        )

    allowed_status = {item[0] for item in COPY_STATUS_CHOICES}
    allowed_have_status = {item[0] for item in COPY_HAVE_STATUS_CHOICES}
    if status not in allowed_status:
        status = "not_sended"
    if have_status not in allowed_have_status:
        have_status = "yes"

    parsed_library_id: int | None = None
    if library_id and str(library_id).strip():
        if not str(library_id).isdigit():
            msg = urllib.parse.quote("Kutubxona qiymati noto'g'ri yuborildi.")
            return RedirectResponse(
                url=f"/books/{book_id}?flash_type=error&flash_msg={msg}",
                status_code=303,
            )
        parsed_library_id = int(library_id)
        library = db.query(Library).filter(Library.id == parsed_library_id).first()
        if not library:
            return RedirectResponse(
                url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Kutubxona topilmadi.')}",
                status_code=303,
            )

    duplicate = (
        db.query(BookCopy.id)
        .filter(BookCopy.inventory_number == inv, BookCopy.id != copy_id)
        .first()
    )
    if duplicate:
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Bunday inventar raqami allaqachon mavjud.')}",
            status_code=303,
        )

    try:
        copy.inventory_number = inv
        copy.status = status
        copy.have_status = have_status
        copy.library_id = parsed_library_id
        db.commit()
        msg = urllib.parse.quote("Nusxa ma'lumotlari yangilandi.")
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=success&flash_msg={msg}",
            status_code=303,
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Xatolik: ' + str(e))}",
            status_code=303,
        )


@router.get("/{book_id}/copies/delete/{copy_id}")
@router.get("/{book_id}/copies/delete/{copy_id}/")
async def delete_book_copy(
    book_id: int,
    copy_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _guard(request)
    if is_book_delete_blocked():
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=warning&flash_msg={urllib.parse.quote('Nusxalarni o‘chirish tizim sozlamalarida vaqtincha taqiqlangan.')}",
            status_code=303,
        )
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return RedirectResponse(
            url=f"/books?flash_type=error&flash_msg={urllib.parse.quote('Kitob topilmadi.')}",
            status_code=303,
        )

    copy = (
        db.query(BookCopy)
        .filter(BookCopy.id == copy_id, BookCopy.original_book_id == book_id)
        .first()
    )
    if not copy:
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Nusxa topilmadi.')}",
            status_code=303,
        )

    if copy.library_id:
        msg = urllib.parse.quote("Nusxa kutubxonaga biriktirilgan. Avval biriktirishni olib tashlang.")
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=warning&flash_msg={msg}",
            status_code=303,
        )

    inv = copy.inventory_number or ""
    try:
        db.delete(copy)
        if (book.total_copies or 0) > 0:
            book.total_copies = int(book.total_copies) - 1
        db.commit()
        msg = urllib.parse.quote(f"Nusxa o'chirildi: {inv}")
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=success&flash_msg={msg}",
            status_code=303,
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=f"/books/{book_id}?flash_type=error&flash_msg={urllib.parse.quote('Xatolik: ' + str(e))}",
            status_code=303,
        )


def _build_copy_transfer_url(
    *,
    q: str | None = None,
    source_library: str | None = None,
    book_type_id: str | int | None = None,
    bbk_id: str | int | None = None,
    author_id: str | int | None = None,
    book_id: str | int | None = None,
    page: int | None = None,
    flash_type: str | None = None,
    flash_msg: str | None = None,
) -> str:
    params: list[tuple[str, str]] = []
    if q and q.strip():
        params.append(("q", q.strip()))
    if source_library and source_library.strip():
        params.append(("source_library", source_library.strip()))
    if book_type_id is not None:
        val = str(book_type_id).strip()
        if val.isdigit():
            params.append(("book_type_id", val))
    if bbk_id is not None:
        val = str(bbk_id).strip()
        if val.isdigit():
            params.append(("bbk_id", val))
    if author_id is not None:
        val = str(author_id).strip()
        if val.isdigit():
            params.append(("author_id", val))
    if book_id is not None:
        val = str(book_id).strip()
        if val.isdigit():
            params.append(("book_id", val))
    if page and page > 1:
        params.append(("page", str(page)))
    if flash_type:
        params.append(("flash_type", flash_type))
    if flash_msg:
        params.append(("flash_msg", flash_msg))

    base_url = "/books/copies/transfer"
    if not params:
        return base_url
    return f"{base_url}?{urllib.parse.urlencode(params)}"


@router.get("/copies/transfer", response_class=HTMLResponse)
@router.get("/copies/transfer/", response_class=HTMLResponse)
async def copy_transfer_hub(
    request: Request,
    page: int = 1,
    per_page: int = 60,
    q: Optional[str] = None,
    source_library: Optional[str] = "__unassigned__",
    book_type_id: Optional[str] = None,
    bbk_id: Optional[str] = None,
    author_id: Optional[str] = None,
    book_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _guard(request)

    per_page = min(max(int(per_page or 60), 20), 200)
    source_key = (source_library or "__unassigned__").strip() or "__unassigned__"
    try:
        book_type_filter = int(book_type_id) if book_type_id else None
    except ValueError:
        book_type_filter = None
    try:
        bbk_filter = int(bbk_id) if bbk_id else None
    except ValueError:
        bbk_filter = None
    try:
        author_filter = int(author_id) if author_id else None
    except ValueError:
        author_filter = None
    try:
        book_filter = int(book_id) if book_id else None
    except ValueError:
        book_filter = None

    query = db.query(BookCopy).join(Book, Book.id == BookCopy.original_book_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter((BookCopy.inventory_number.ilike(pattern)) | (Book.title.ilike(pattern)))

    if source_key == "__unassigned__":
        query = query.filter(BookCopy.library_id.is_(None))
    elif source_key == "__all__":
        pass
    elif source_key.isdigit():
        query = query.filter(BookCopy.library_id == int(source_key))
    else:
        source_key = "__unassigned__"
        query = query.filter(BookCopy.library_id.is_(None))

    if book_type_filter:
        query = query.filter(Book.book_type_id == book_type_filter)
    if bbk_filter:
        query = query.filter(Book.bbk_id == bbk_filter)
    if author_filter:
        query = query.filter(Book.authors.any(Author.id == author_filter))
    if book_filter:
        query = query.filter(Book.id == book_filter)

    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    if page < 1:
        page = 1
    if total_pages and page > total_pages:
        page = total_pages

    copies = (
        query.order_by(BookCopy.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    libraries = db.query(Library).order_by(Library.name).all()
    book_types = db.query(BookType).order_by(BookType.name).all()
    bbks = db.query(BBK).order_by(BBK.code, BBK.name).all()
    authors = db.query(Author).order_by(Author.name).all()
    books_for_filter = db.query(Book.id, Book.title).order_by(Book.title).all()
    selected_book_type = (
        db.query(BookType).filter(BookType.id == book_type_filter).first()
        if book_type_filter else None
    )
    selected_bbk = db.query(BBK).filter(BBK.id == bbk_filter).first() if bbk_filter else None
    selected_author = (
        db.query(Author).filter(Author.id == author_filter).first()
        if author_filter else None
    )
    selected_book = db.query(Book).filter(Book.id == book_filter).first() if book_filter else None
    status_labels = dict(COPY_STATUS_CHOICES)
    have_status_labels = dict(COPY_HAVE_STATUS_CHOICES)
    unassigned_count = db.query(BookCopy.id).filter(BookCopy.library_id.is_(None)).count()
    assigned_count = db.query(BookCopy.id).filter(BookCopy.library_id.isnot(None)).count()

    page_query: list[str] = []
    if q and q.strip():
        page_query.append(f"q={urllib.parse.quote(q.strip())}")
    if source_key:
        page_query.append(f"source_library={urllib.parse.quote(source_key)}")
    if book_type_filter:
        page_query.append(f"book_type_id={book_type_filter}")
    if bbk_filter:
        page_query.append(f"bbk_id={bbk_filter}")
    if author_filter:
        page_query.append(f"author_id={author_filter}")
    if book_filter:
        page_query.append(f"book_id={book_filter}")
    page_url_base = f"?{'&'.join(page_query)}&page=" if page_query else "?page="

    return templates.TemplateResponse(
        "books/copy_transfer.html",
        _ctx(
            request,
            title="Nusxalarni biriktirish",
            active_menu="books",
            copies=copies,
            libraries=libraries,
            book_types=book_types,
            bbks=bbks,
            authors=authors,
            books_for_filter=books_for_filter,
            q=q or "",
            source_library=source_key,
            book_type_id=book_type_filter or "",
            bbk_id=bbk_filter or "",
            author_id=author_filter or "",
            book_id=book_filter or "",
            selected_book_type_label=selected_book_type.name if selected_book_type else "",
            selected_bbk_label=(
                f"{selected_bbk.code} - {selected_bbk.name}" if selected_bbk else ""
            ),
            selected_author_label=selected_author.name if selected_author else "",
            selected_book_label=selected_book.title if selected_book else "",
            page=page,
            per_page=per_page,
            total_items=total,
            total_pages=total_pages,
            page_url_base=page_url_base,
            status_labels=status_labels,
            have_status_labels=have_status_labels,
            unassigned_count=unassigned_count,
            assigned_count=assigned_count,
        ),
    )


@router.post("/copies/transfer")
@router.post("/copies/transfer/")
async def copy_transfer_execute(
    request: Request,
    target_library_id: int = Form(...),
    copy_ids: list[int] = Form(default=[]),
    q: Optional[str] = Form(None),
    source_library: Optional[str] = Form("__unassigned__"),
    book_type_id: Optional[str] = Form(None),
    bbk_id: Optional[str] = Form(None),
    author_id: Optional[str] = Form(None),
    book_id: Optional[str] = Form(None),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    _guard(request)

    target_library = db.query(Library).filter(Library.id == target_library_id).first()
    if not target_library:
        return RedirectResponse(
            url=_build_copy_transfer_url(
                q=q,
                source_library=source_library,
                book_type_id=book_type_id,
                bbk_id=bbk_id,
                author_id=author_id,
                book_id=book_id,
                page=page,
                flash_type="error",
                flash_msg="Tanlangan kutubxona topilmadi.",
            ),
            status_code=303,
        )

    selected_ids = sorted({int(cid) for cid in copy_ids if int(cid) > 0})
    if not selected_ids:
        return RedirectResponse(
            url=_build_copy_transfer_url(
                q=q,
                source_library=source_library,
                book_type_id=book_type_id,
                bbk_id=bbk_id,
                author_id=author_id,
                book_id=book_id,
                page=page,
                flash_type="warning",
                flash_msg="Kamida bitta nusxani tanlang.",
            ),
            status_code=303,
        )

    copies = db.query(BookCopy).filter(BookCopy.id.in_(selected_ids)).all()
    if not copies:
        return RedirectResponse(
            url=_build_copy_transfer_url(
                q=q,
                source_library=source_library,
                book_type_id=book_type_id,
                bbk_id=bbk_id,
                author_id=author_id,
                book_id=book_id,
                page=page,
                flash_type="error",
                flash_msg="Tanlangan nusxalar topilmadi.",
            ),
            status_code=303,
        )

    moved_count = 0
    unchanged_count = 0

    try:
        for copy in copies:
            if copy.library_id == target_library.id:
                unchanged_count += 1
                continue
            copy.library_id = target_library.id
            moved_count += 1

        db.commit()

        msg = f"{moved_count} ta nusxa \"{target_library.name}\" kutubxonasiga biriktirildi."
        if unchanged_count > 0:
            msg += f" {unchanged_count} tasi allaqachon shu kutubxonada edi."

        return RedirectResponse(
            url=_build_copy_transfer_url(
                q=q,
                source_library=source_library,
                book_type_id=book_type_id,
                bbk_id=bbk_id,
                author_id=author_id,
                book_id=book_id,
                page=page,
                flash_type="success",
                flash_msg=msg,
            ),
            status_code=303,
        )
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            url=_build_copy_transfer_url(
                q=q,
                source_library=source_library,
                book_type_id=book_type_id,
                bbk_id=bbk_id,
                author_id=author_id,
                book_id=book_id,
                page=page,
                flash_type="error",
                flash_msg=f"Xatolik: {str(exc)}",
            ),
            status_code=303,
        )
