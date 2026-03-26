from fastapi import APIRouter, Request, Depends, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import os
import shutil
import urllib.parse
import uuid

from app.core.database import get_db
from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.core.system_settings import is_book_delete_blocked
from app.models.library import (
    OnlineBook,
    BookEdition,
    Author,
    BookType,
    BBK,
    Publisher,
    PublishedCity,
    PublicationYear,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
UPLOAD_DIR = "app/static/uploads/online_books"
os.makedirs(UPLOAD_DIR, exist_ok=True)
LANGUAGE_OPTIONS = [
    ("uz", "O'zbek (lotin)"),
    ("oz", "O'zbek (kirill)"),
    ("ru", "Rus"),
    ("en", "Ingliz"),
    ("tr", "Turk"),
    ("fr", "Fransuz"),
    ("de", "Nemis"),
    ("zh", "Xitoy"),
    ("ar", "Arab"),
    ("kk", "Qozoq"),
    ("ky", "Qirg'iz"),
]
LANGUAGE_LABELS = dict(LANGUAGE_OPTIONS)
EDITION_STATUS_OPTIONS = [
    ("undistributed", "Tarqatilmagan"),
    ("distributed", "Tarqatilgan"),
]
EDITION_STATUS_LABELS = dict(EDITION_STATUS_OPTIONS)


def _guard(request: Request, menu_key: str = "online_books"):
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


def _save_file(upload: UploadFile | None, sub: str) -> str | None:
    if not upload or not upload.filename:
        return None
    ext = os.path.splitext(upload.filename)[-1]
    name = f"{uuid.uuid4().hex}{ext}"
    dst = os.path.join(UPLOAD_DIR, sub, name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return f"/static/uploads/online_books/{sub}/{name}"


def _latest_edition(db: Session, book_id: int) -> Optional[BookEdition]:
    return (
        db.query(BookEdition)
        .filter(BookEdition.book_id == book_id)
        .order_by(BookEdition.id.desc())
        .first()
    )


def _int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def list_online_books(
    request: Request,
    page: int = 1,
    per_page: int = 50,
    q: Optional[str] = None,
    language: Optional[str] = None,
    type_id: Optional[str] = None,
    author_id: Optional[str] = None,
    bbk_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _guard(request)

    try: type_id = int(type_id) if type_id else None
    except ValueError: type_id = None
    
    try: author_id = int(author_id) if author_id else None
    except ValueError: author_id = None
    
    try: bbk_id = int(bbk_id) if bbk_id else None
    except ValueError: bbk_id = None

    per_page = 50
    query = db.query(OnlineBook)

    if q:
        query = query.filter(OnlineBook.title.ilike(f"%{q}%"))
    if language:
        query = query.filter(OnlineBook.language == language)
    if type_id:
        query = query.filter(OnlineBook.book_type_id == type_id)
    if bbk_id:
        query = query.filter(OnlineBook.bbk_id == bbk_id)
    if author_id:
        query = query.filter(OnlineBook.authors.any(Author.id == author_id))

    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    if page < 1:
        page = 1
    if total_pages and page > total_pages:
        page = total_pages

    items = (
        query.order_by(OnlineBook.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    for item in items:
        item_lang = str(item.language or "").strip().lower()
        item.authors_text = ", ".join(a.name for a in (item.authors or [])[:2]) if item.authors else "-"
        item.editions_count = len(item.editions or [])
        item.adad_value = sum(int(ed.adad or 0) for ed in (item.editions or []))
        item.language_name = LANGUAGE_LABELS.get(item_lang, item_lang.upper() if item_lang else "-")
        item.has_image = any(bool((ed.image or "").strip()) for ed in (item.editions or []))
        item.has_file = any(bool((ed.file or "").strip()) for ed in (item.editions or []))
        item.has_audio = any(bool((ed.audio_file or "").strip()) for ed in (item.editions or []))

    types = db.query(BookType).filter(BookType.is_active == True).order_by(BookType.name).all()
    bbks = db.query(BBK).filter(BBK.is_active == True).order_by(BBK.name).all()
    authors = db.query(Author).filter(Author.is_active == True).order_by(Author.name).all()

    langs_raw = (
        db.query(OnlineBook.language)
        .filter(OnlineBook.language.isnot(None))
        .distinct()
        .all()
    )
    languages = sorted([str(row[0]).lower() for row in langs_raw if str(row[0]).strip()])

    query_parts: list[str] = []
    if q:
        query_parts.append(f"q={urllib.parse.quote(str(q))}")
    if language:
        query_parts.append(f"language={urllib.parse.quote(str(language))}")
    if type_id:
        query_parts.append(f"type_id={int(type_id)}")
    if author_id:
        query_parts.append(f"author_id={int(author_id)}")
    if bbk_id:
        query_parts.append(f"bbk_id={int(bbk_id)}")
    page_url_base = f"?{'&'.join(query_parts)}&page=" if query_parts else "?page="

    return templates.TemplateResponse(
        "online_books/list.html",
        _ctx(
            request,
            title="Online kitoblar",
            active_menu="online_books",
            items=items,
            q=q or "",
            language=language or "",
            type_id=type_id or "",
            author_id=author_id or "",
            bbk_id=bbk_id or "",
            languages=languages,
            language_labels=LANGUAGE_LABELS,
            types=types,
            bbks=bbks,
            authors=authors,
            page=page,
            total_pages=total_pages,
            total_items=total,
            per_page=per_page,
            page_url_base=page_url_base,
        ),
    )


@router.get("/add", response_class=HTMLResponse)
@router.get("/add/", response_class=HTMLResponse)
async def add_online_book_page(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    return templates.TemplateResponse(
        "online_books/add.html",
        _ctx(
            request,
            title="Yangi Online Kitob",
            active_menu="online_books",
            authors=db.query(Author).filter(Author.is_active == True).order_by(Author.name).all(),
            book_types=db.query(BookType).filter(BookType.is_active == True).order_by(BookType.name).all(),
            bbks=db.query(BBK).filter(BBK.is_active == True).order_by(BBK.name).all(),
            publishers=db.query(Publisher).filter(Publisher.is_active == True).order_by(Publisher.name).all(),
            cities=db.query(PublishedCity).filter(PublishedCity.is_active == True).order_by(PublishedCity.name).all(),
            years=db.query(PublicationYear).filter(PublicationYear.is_active == True).order_by(PublicationYear.year.desc()).all(),
            languages=LANGUAGE_OPTIONS,
            language_labels=LANGUAGE_LABELS,
            edit_mode=False,
            item=None,
            edition=None,
            selected_book_type_label="",
            selected_bbk_label="",
            selected_publisher_label="",
            selected_city_label="",
            selected_year_label="",
            selected_language_name=LANGUAGE_LABELS.get("uz", "O'zbek (lotin)"),
        ),
    )


@router.get("/edit/{book_id}", response_class=HTMLResponse)
@router.get("/edit/{book_id}/", response_class=HTMLResponse)
async def edit_online_book_page(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    edition = _latest_edition(db, book.id)

    book_type_obj = db.query(BookType).filter(BookType.id == book.book_type_id).first() if book.book_type_id else None
    bbk_obj = db.query(BBK).filter(BBK.id == book.bbk_id).first() if book.bbk_id else None
    publisher_obj = db.query(Publisher).filter(Publisher.id == edition.publisher_id).first() if edition and edition.publisher_id else None
    city_obj = db.query(PublishedCity).filter(PublishedCity.id == edition.published_city_id).first() if edition and edition.published_city_id else None
    year_obj = db.query(PublicationYear).filter(PublicationYear.id == edition.publication_year_id).first() if edition and edition.publication_year_id else None

    language_code = (book.language or "uz").strip().lower()
    language_labels = LANGUAGE_LABELS
    selected_language_name = language_labels.get(language_code, language_code.upper() if language_code else "UZ")

    return templates.TemplateResponse(
        "online_books/add.html",
        _ctx(
            request,
            title=f"Online Kitobni Tahrirlash: {book.title}",
            active_menu="online_books",
            authors=db.query(Author).filter(Author.is_active == True).order_by(Author.name).all(),
            book_types=db.query(BookType).filter(BookType.is_active == True).order_by(BookType.name).all(),
            bbks=db.query(BBK).filter(BBK.is_active == True).order_by(BBK.name).all(),
            publishers=db.query(Publisher).filter(Publisher.is_active == True).order_by(Publisher.name).all(),
            cities=db.query(PublishedCity).filter(PublishedCity.is_active == True).order_by(PublishedCity.name).all(),
            years=db.query(PublicationYear).filter(PublicationYear.is_active == True).order_by(PublicationYear.year.desc()).all(),
            languages=LANGUAGE_OPTIONS,
            language_labels=language_labels,
            edit_mode=True,
            item=book,
            edition=edition,
            selected_book_type_label=book_type_obj.name if book_type_obj else "",
            selected_bbk_label=(f"{bbk_obj.code} - {bbk_obj.name}" if bbk_obj else ""),
            selected_publisher_label=publisher_obj.name if publisher_obj else "",
            selected_city_label=city_obj.name if city_obj else "",
            selected_year_label=str(year_obj.year) if year_obj else "",
            selected_language_name=selected_language_name,
        ),
    )


@router.get("/{book_id}", response_class=HTMLResponse)
@router.get("/{book_id}/", response_class=HTMLResponse)
async def view_online_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    edition = _latest_edition(db, book.id)
    editions = (
        db.query(BookEdition)
        .filter(BookEdition.book_id == book.id)
        .order_by(BookEdition.id.desc())
        .all()
    )

    language_code = (book.language or "").strip().lower()
    language_name = LANGUAGE_LABELS.get(language_code, language_code.upper() if language_code else "-")
    publisher_name = ""
    city_name = ""
    year_value = ""
    if edition:
        if edition.publisher_id:
            pub = db.query(Publisher).filter(Publisher.id == edition.publisher_id).first()
            publisher_name = pub.name if pub else ""
        if edition.published_city_id:
            city = db.query(PublishedCity).filter(PublishedCity.id == edition.published_city_id).first()
            city_name = city.name if city else ""
        if edition.publication_year_id:
            year = db.query(PublicationYear).filter(PublicationYear.id == edition.publication_year_id).first()
            year_value = str(year.year) if year else ""

    book_type_name = ""
    bbk_text = ""
    if book.book_type_id:
        bt = db.query(BookType).filter(BookType.id == book.book_type_id).first()
        book_type_name = bt.name if bt else ""
    if book.bbk_id:
        bbk = db.query(BBK).filter(BBK.id == book.bbk_id).first()
        bbk_text = f"{bbk.code} - {bbk.name}" if bbk else ""
    authors_text = ", ".join(a.name for a in (book.authors or []))
    file_url = (edition.file if edition and edition.file else "") if edition else ""
    file_is_pdf = file_url.lower().endswith(".pdf") if file_url else False

    edition_publisher_ids = {ed.publisher_id for ed in editions if ed.publisher_id}
    edition_city_ids = {ed.published_city_id for ed in editions if ed.published_city_id}
    edition_year_ids = {ed.publication_year_id for ed in editions if ed.publication_year_id}

    publisher_map = {}
    if edition_publisher_ids:
        publisher_map = {
            obj.id: obj.name
            for obj in db.query(Publisher).filter(Publisher.id.in_(edition_publisher_ids)).all()
        }

    city_map = {}
    if edition_city_ids:
        city_map = {
            obj.id: obj.name
            for obj in db.query(PublishedCity).filter(PublishedCity.id.in_(edition_city_ids)).all()
        }

    year_map = {}
    if edition_year_ids:
        year_map = {
            obj.id: str(obj.year)
            for obj in db.query(PublicationYear).filter(PublicationYear.id.in_(edition_year_ids)).all()
        }

    for ed in editions:
        ed.publisher_name = publisher_map.get(ed.publisher_id, "-")
        ed.city_name = city_map.get(ed.published_city_id, "-")
        ed.year_label = year_map.get(ed.publication_year_id, "-")
        ed.file_is_pdf = bool((ed.file or "").strip().lower().endswith(".pdf"))
        ed.status_label = EDITION_STATUS_LABELS.get(ed.status or "", ed.status or "-")

    publishers = db.query(Publisher).filter(Publisher.is_active == True).order_by(Publisher.name).all()
    cities = db.query(PublishedCity).filter(PublishedCity.is_active == True).order_by(PublishedCity.name).all()
    years = db.query(PublicationYear).filter(PublicationYear.is_active == True).order_by(PublicationYear.year.desc()).all()

    active_publisher_ids = {row.id for row in publishers}
    active_city_ids = {row.id for row in cities}
    active_year_ids = {row.id for row in years}

    missing_publisher_ids = edition_publisher_ids - active_publisher_ids
    missing_city_ids = edition_city_ids - active_city_ids
    missing_year_ids = edition_year_ids - active_year_ids

    if missing_publisher_ids:
        publishers.extend(
            db.query(Publisher).filter(Publisher.id.in_(missing_publisher_ids)).order_by(Publisher.name).all()
        )
        publishers = sorted(publishers, key=lambda row: (row.name or "").casefold())

    if missing_city_ids:
        cities.extend(
            db.query(PublishedCity).filter(PublishedCity.id.in_(missing_city_ids)).order_by(PublishedCity.name).all()
        )
        cities = sorted(cities, key=lambda row: (row.name or "").casefold())

    if missing_year_ids:
        years.extend(
            db.query(PublicationYear).filter(PublicationYear.id.in_(missing_year_ids)).order_by(PublicationYear.year.desc()).all()
        )
        years = sorted(years, key=lambda row: row.year or 0, reverse=True)

    return templates.TemplateResponse(
        "online_books/view.html",
        _ctx(
            request,
            title=f"Online kitob: {book.title}",
            active_menu="online_books",
            item=book,
            edition=edition,
            language_code=language_code,
            language_name=language_name,
            publisher_name=publisher_name,
            city_name=city_name,
            year_value=year_value,
            book_type_name=book_type_name,
            bbk_text=bbk_text,
            authors_text=authors_text,
            file_url=file_url,
            file_is_pdf=file_is_pdf,
            editions=editions,
            publishers=publishers,
            cities=cities,
            years=years,
            edition_statuses=EDITION_STATUS_OPTIONS,
        ),
    )


@router.post("/add")
@router.post("/add/")
async def add_online_book(
    request: Request,
    title: str = Form(...),
    language: str = Form("uz"),
    isbn: Optional[str] = Form(None),
    annotation: Optional[str] = Form(None),
    book_type_id: Optional[int] = Form(None),
    bbk_id: Optional[int] = Form(None),
    author_ids: list[int] = Form(default=[]),
    pages: Optional[int] = Form(None),
    adad: Optional[int] = Form(0),
    publication_year_id: Optional[int] = Form(None),
    publisher_id: Optional[int] = Form(None),
    published_city_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    audio_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    user = _guard(request)

    clean_title = (title or "").strip()
    if not clean_title:
        msg = urllib.parse.quote("Online kitob nomini kiriting.")
        return RedirectResponse(url=f"/online-books/add?flash_type=error&flash_msg={msg}", status_code=303)

    book = OnlineBook(
        title=clean_title,
        language=((language or "uz").strip().lower() or "uz"),
        isbn=(isbn or "").strip() or None,
        annotation=annotation,
        bbk_id=bbk_id,
        book_type_id=book_type_id,
        added_by_id=user["id"],
    )
    if author_ids:
        found_authors = db.query(Author).filter(Author.id.in_(author_ids)).all()
        book.authors = found_authors

    try:
        db.add(book)
        db.flush()

        edition = BookEdition(
            book_id=book.id,
            pages=pages,
            adad=int(adad or 0),
            publication_year_id=publication_year_id,
            publisher_id=publisher_id,
            published_city_id=published_city_id,
        )
        edition.image = _save_file(image, "images")
        edition.file = _save_file(file, "files")
        edition.audio_file = _save_file(audio_file, "audio")
        db.add(edition)

        db.commit()
        msg = urllib.parse.quote("Online kitob muvaffaqiyatli qo'shildi.")
        return RedirectResponse(url=f"/online-books?flash_type=success&flash_msg={msg}", status_code=303)
    except Exception as exc:
        db.rollback()
        msg = urllib.parse.quote(f"Xatolik: {str(exc)}")
        return RedirectResponse(url=f"/online-books/add?flash_type=error&flash_msg={msg}", status_code=303)


@router.post("/edit/{book_id}")
@router.post("/edit/{book_id}/")
async def edit_online_book(
    book_id: int,
    request: Request,
    title: str = Form(...),
    language: str = Form("uz"),
    isbn: Optional[str] = Form(None),
    annotation: Optional[str] = Form(None),
    book_type_id: Optional[int] = Form(None),
    bbk_id: Optional[int] = Form(None),
    author_ids: list[int] = Form(default=[]),
    pages: Optional[int] = Form(None),
    adad: Optional[int] = Form(0),
    publication_year_id: Optional[int] = Form(None),
    publisher_id: Optional[int] = Form(None),
    published_city_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    audio_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    _guard(request)
    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    clean_title = (title or "").strip()
    if not clean_title:
        msg = urllib.parse.quote("Online kitob nomini kiriting.")
        return RedirectResponse(url=f"/online-books/edit/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    try:
        book.title = clean_title
        book.language = ((language or "uz").strip().lower() or "uz")
        book.isbn = (isbn or "").strip() or None
        book.annotation = annotation
        book.book_type_id = book_type_id
        book.bbk_id = bbk_id
        book.authors = db.query(Author).filter(Author.id.in_(author_ids)).all() if author_ids else []

        edition = _latest_edition(db, book.id)
        if not edition:
            edition = BookEdition(book_id=book.id)
            db.add(edition)

        edition.pages = pages
        edition.adad = int(adad or 0)
        edition.publication_year_id = publication_year_id
        edition.publisher_id = publisher_id
        edition.published_city_id = published_city_id

        if image and image.filename:
            edition.image = _save_file(image, "images")
        if file and file.filename:
            edition.file = _save_file(file, "files")
        if audio_file and audio_file.filename:
            edition.audio_file = _save_file(audio_file, "audio")

        db.commit()
        msg = urllib.parse.quote("Online kitob ma'lumotlari saqlandi.")
        return RedirectResponse(url=f"/online-books?flash_type=success&flash_msg={msg}", status_code=303)
    except Exception as exc:
        db.rollback()
        msg = urllib.parse.quote(f"Xatolik: {str(exc)}")
        return RedirectResponse(url=f"/online-books/edit/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)


@router.post("/{book_id}/editions/{edition_id}/edit")
@router.post("/{book_id}/editions/{edition_id}/edit/")
async def edit_online_book_edition(
    book_id: int,
    edition_id: int,
    request: Request,
    pages: Optional[int] = Form(None),
    adad: Optional[int] = Form(0),
    status: str = Form("undistributed"),
    publication_year_id: Optional[str] = Form(None),
    publisher_id: Optional[str] = Form(None),
    published_city_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    audio_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    _guard(request)

    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    edition = (
        db.query(BookEdition)
        .filter(BookEdition.id == edition_id, BookEdition.book_id == book_id)
        .first()
    )
    if not edition:
        msg = urllib.parse.quote("Versiya topilmadi.")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    try:
        edition.pages = pages
        edition.adad = int(adad or 0)
        normalized_status = (status or "undistributed").strip().lower()
        if normalized_status not in EDITION_STATUS_LABELS:
            normalized_status = "undistributed"
        edition.status = normalized_status
        edition.publication_year_id = _int_or_none(publication_year_id)
        edition.publisher_id = _int_or_none(publisher_id)
        edition.published_city_id = _int_or_none(published_city_id)

        if image and image.filename:
            edition.image = _save_file(image, "images")
        if file and file.filename:
            edition.file = _save_file(file, "files")
        if audio_file and audio_file.filename:
            edition.audio_file = _save_file(audio_file, "audio")

        db.commit()
        msg = urllib.parse.quote(f"Versiya yangilandi (ID: {edition_id}).")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=success&flash_msg={msg}", status_code=303)
    except Exception as exc:
        db.rollback()
        msg = urllib.parse.quote(f"Versiyani saqlashda xatolik: {str(exc)}")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)


@router.post("/{book_id}/editions/add")
@router.post("/{book_id}/editions/add/")
async def add_online_book_edition(
    book_id: int,
    request: Request,
    pages: Optional[int] = Form(None),
    adad: Optional[int] = Form(0),
    status: str = Form("undistributed"),
    publication_year_id: Optional[str] = Form(None),
    publisher_id: Optional[str] = Form(None),
    published_city_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    audio_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    _guard(request)

    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    try:
        normalized_status = (status or "undistributed").strip().lower()
        if normalized_status not in EDITION_STATUS_LABELS:
            normalized_status = "undistributed"

        edition = BookEdition(
            book_id=book.id,
            pages=pages,
            adad=int(adad or 0),
            status=normalized_status,
            publication_year_id=_int_or_none(publication_year_id),
            publisher_id=_int_or_none(publisher_id),
            published_city_id=_int_or_none(published_city_id),
        )
        if image and image.filename:
            edition.image = _save_file(image, "images")
        if file and file.filename:
            edition.file = _save_file(file, "files")
        if audio_file and audio_file.filename:
            edition.audio_file = _save_file(audio_file, "audio")

        db.add(edition)
        db.commit()
        msg = urllib.parse.quote(f"Yangi versiya qo'shildi (ID: {edition.id}).")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=success&flash_msg={msg}", status_code=303)
    except Exception as exc:
        db.rollback()
        msg = urllib.parse.quote(f"Versiya qo'shishda xatolik: {str(exc)}")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)


@router.get("/{book_id}/editions/{edition_id}/delete")
@router.get("/{book_id}/editions/{edition_id}/delete/")
async def delete_online_book_edition(book_id: int, edition_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    if is_book_delete_blocked():
        msg = urllib.parse.quote("Kitob o'chirish amali tizim sozlamalarida vaqtincha taqiqlangan.")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=warning&flash_msg={msg}", status_code=303)

    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    edition = (
        db.query(BookEdition)
        .filter(BookEdition.id == edition_id, BookEdition.book_id == book_id)
        .first()
    )
    if not edition:
        msg = urllib.parse.quote("Versiya topilmadi.")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)

    try:
        db.delete(edition)
        db.commit()
        msg = urllib.parse.quote(f"Versiya o'chirildi (ID: {edition_id}).")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=success&flash_msg={msg}", status_code=303)
    except Exception as exc:
        db.rollback()
        msg = urllib.parse.quote(f"Versiyani o'chirishda xatolik: {str(exc)}")
        return RedirectResponse(url=f"/online-books/{book_id}?flash_type=error&flash_msg={msg}", status_code=303)


@router.get("/delete/{book_id}")
@router.get("/delete/{book_id}/")
async def delete_online_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    if is_book_delete_blocked():
        msg = urllib.parse.quote("Kitob o'chirish amali tizim sozlamalarida vaqtincha taqiqlangan.")
        return RedirectResponse(url=f"/online-books?flash_type=warning&flash_msg={msg}", status_code=303)
    book = db.query(OnlineBook).filter(OnlineBook.id == book_id).first()
    if not book:
        msg = urllib.parse.quote("Online kitob topilmadi.")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)

    try:
        # M2M bog'lanishlarni tozalaymiz, keyin kitobni o'chiramiz.
        book.authors = []
        db.flush()
        db.delete(book)
        db.commit()
        msg = urllib.parse.quote("Online kitob o'chirildi.")
        return RedirectResponse(url=f"/online-books?flash_type=success&flash_msg={msg}", status_code=303)
    except Exception as exc:
        db.rollback()
        msg = urllib.parse.quote(f"O'chirishda xatolik: {str(exc)}")
        return RedirectResponse(url=f"/online-books?flash_type=error&flash_msg={msg}", status_code=303)
