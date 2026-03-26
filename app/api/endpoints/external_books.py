from __future__ import annotations

import asyncio
import mimetypes
import os
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.core.database import SessionLocal, get_db
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from app.models.library import (
    Author,
    BBK,
    Book,
    BookCopy,
    BookEdition,
    BookType,
    Library,
    OnlineBook,
    PublicationYear,
    PublishedCity,
    Publisher,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PRINTED_IMG_DIR = os.path.join("app", "static", "uploads", "books", "images")
PRINTED_FILE_DIR = os.path.join("app", "static", "uploads", "books", "files")
ONLINE_IMG_DIR = os.path.join("app", "static", "uploads", "online_books", "images")
ONLINE_FILE_DIR = os.path.join("app", "static", "uploads", "online_books", "files")
ONLINE_AUDIO_DIR = os.path.join("app", "static", "uploads", "online_books", "audio")

for _dir in [PRINTED_IMG_DIR, PRINTED_FILE_DIR, ONLINE_IMG_DIR, ONLINE_FILE_DIR, ONLINE_AUDIO_DIR]:
    os.makedirs(_dir, exist_ok=True)

VALID_COPY_STATUSES = {"accepted", "sent", "not_accepted", "not_sended", "active", "lost"}
VALID_COPY_HAVE_STATUSES = {"yes", "busy", "no"}
VALID_EDITION_STATUSES = {"distributed", "undistributed"}
IMPORT_JOB_TTL_SECONDS = 3600
IMPORT_JOB_MAX = 200
IMPORT_JOBS: dict[str, dict[str, Any]] = {}
IMPORT_WORKER_COUNT = 1
IMPORT_JOB_QUEUE: asyncio.Queue[str] | None = None
IMPORT_WORKER_TASKS: list[asyncio.Task[Any]] = []
IMPORT_WORKER_LOCK: asyncio.Lock | None = None
DOWNLOAD_CONCURRENCY = 8
DOWNLOAD_SEMAPHORE: asyncio.Semaphore | None = None


def _base_ctx(request: Request, **extra):
    return {"request": request, "session_user": get_session_user(request), **extra}


def _ensure_access(request: Request) -> dict:
    session_user = get_session_user(request)
    if not session_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not can_access_menu(session_user, "external_books"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return session_user


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup_import_jobs() -> None:
    now_ts = time.time()
    stale_ids: list[str] = []
    for job_id, job in IMPORT_JOBS.items():
        status = _s(job.get("status")).lower()
        updated_ts = float(job.get("updated_ts") or now_ts)
        if status in {"done", "error", "cancelled"} and (now_ts - updated_ts) > IMPORT_JOB_TTL_SECONDS:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        IMPORT_JOBS.pop(job_id, None)

    if len(IMPORT_JOBS) <= IMPORT_JOB_MAX:
        return

    removable = sorted(
        (
            pair
            for pair in IMPORT_JOBS.items()
            if _s(pair[1].get("status")).lower() in {"done", "error", "cancelled"}
        ),
        key=lambda pair: float(pair[1].get("updated_ts") or 0.0),
    )
    overflow = len(IMPORT_JOBS) - IMPORT_JOB_MAX
    if overflow <= 0:
        return
    for job_id, _ in removable[:overflow]:
        IMPORT_JOBS.pop(job_id, None)


def _extract_import_meta(payload: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(payload)
    items = _as_list(data.get("items"))
    single_item = _as_dict(data.get("item"))
    selected_count = len(items)
    if selected_count == 0 and single_item:
        selected_count = 1

    return {
        "source_url": _s(data.get("source_url")),
        "book_type": _s(data.get("book_type") or data.get("bookType") or data.get("external_type")),
        "import_all": _to_bool(
            data.get("import_all") if "import_all" in data else data.get("importAll"),
            False,
        ),
        "selected_count": selected_count,
    }


def _job_owned_by_user(job: dict[str, Any], user_id: int | None) -> bool:
    job_user_id = _to_int(job.get("user_id"), 0) or None
    if user_id is None:
        return job_user_id is None
    return job_user_id == user_id


def _find_latest_user_job(user_id: int | None, *, include_finished: bool = False) -> dict[str, Any] | None:
    _cleanup_import_jobs()
    jobs = [job for job in IMPORT_JOBS.values() if _job_owned_by_user(job, user_id)]
    if not jobs:
        return None

    active_jobs = [
        job
        for job in jobs
        if _s(job.get("status")).lower() in {"queued", "running"}
    ]
    if active_jobs:
        active_jobs.sort(
            key=lambda job: (
                0 if _s(job.get("status")).lower() == "running" else 1,
                -float(job.get("updated_ts") or 0.0),
            )
        )
        return active_jobs[0]

    if not include_finished:
        return None

    finished = [
        job
        for job in jobs
        if _s(job.get("status")).lower() in {"done", "error", "cancelled"}
    ]
    if not finished:
        return None
    finished.sort(key=lambda job: float(job.get("updated_ts") or 0.0), reverse=True)
    return finished[0]


def _create_import_job(user_id: int | None, payload: dict[str, Any]) -> dict[str, Any]:
    _cleanup_import_jobs()
    job_id = uuid.uuid4().hex
    now = _utc_iso()
    job = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "queued",
        "phase": "queued",
        "queue_position": 0,
        "progress_percent": 0,
        "processed": 0,
        "total": 0,
        "message": "Navbatga qo'shildi.",
        "payload": payload,
        "meta": _extract_import_meta(payload),
        "result": None,
        "errors": [],
        "created_at": now,
        "updated_at": now,
        "updated_ts": time.time(),
    }
    IMPORT_JOBS[job_id] = job
    return job


def _touch_job(job: dict[str, Any], **updates: Any) -> None:
    job.update(updates)
    job["updated_at"] = _utc_iso()
    job["updated_ts"] = time.time()


def _job_public_data(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "phase": job.get("phase"),
        "queue_position": _to_int(job.get("queue_position"), 0),
        "progress_percent": _to_int(job.get("progress_percent"), 0),
        "processed": _to_int(job.get("processed"), 0),
        "total": _to_int(job.get("total"), 0),
        "message": _s(job.get("message")),
        "result": job.get("result"),
        "errors": _as_list(job.get("errors"))[:20],
        "meta": _as_dict(job.get("meta")),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def _get_download_semaphore() -> asyncio.Semaphore:
    global DOWNLOAD_SEMAPHORE
    if DOWNLOAD_SEMAPHORE is None:
        DOWNLOAD_SEMAPHORE = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    return DOWNLOAD_SEMAPHORE


async def _import_worker_loop(worker_no: int) -> None:
    global IMPORT_JOB_QUEUE
    while True:
        if IMPORT_JOB_QUEUE is None:
            await asyncio.sleep(0.2)
            continue

        job_id = await IMPORT_JOB_QUEUE.get()
        try:
            job = IMPORT_JOBS.get(job_id)
            if not job:
                continue
            _touch_job(
                job,
                status="queued",
                phase="queued",
                queue_position=0,
                message=f"Worker-{worker_no}: navbatdan olindi.",
            )
            await _run_import_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            job = IMPORT_JOBS.get(job_id)
            if job:
                _touch_job(
                    job,
                    status="error",
                    phase="error",
                    queue_position=0,
                    message=f"Worker xatosi: {str(exc)}",
                    errors=[{"message": str(exc)}],
                )
        finally:
            if IMPORT_JOB_QUEUE is not None:
                IMPORT_JOB_QUEUE.task_done()


async def _ensure_import_workers() -> None:
    global IMPORT_JOB_QUEUE, IMPORT_WORKER_LOCK, IMPORT_WORKER_TASKS
    if IMPORT_WORKER_LOCK is None:
        IMPORT_WORKER_LOCK = asyncio.Lock()

    async with IMPORT_WORKER_LOCK:
        if IMPORT_JOB_QUEUE is None:
            IMPORT_JOB_QUEUE = asyncio.Queue()
        IMPORT_WORKER_TASKS = [task for task in IMPORT_WORKER_TASKS if not task.done()]
        if len(IMPORT_WORKER_TASKS) >= IMPORT_WORKER_COUNT:
            return

        missing = IMPORT_WORKER_COUNT - len(IMPORT_WORKER_TASKS)
        for idx in range(missing):
            worker_no = len(IMPORT_WORKER_TASKS) + idx + 1
            task = asyncio.create_task(_import_worker_loop(worker_no), name=f"external-import-worker-{worker_no}")
            IMPORT_WORKER_TASKS.append(task)


async def _enqueue_import_job(job: dict[str, Any]) -> int:
    await _ensure_import_workers()
    if IMPORT_JOB_QUEUE is None:
        raise HTTPException(status_code=500, detail="Import worker navbati ishga tushmadi.")

    try:
        IMPORT_JOB_QUEUE.put_nowait(_s(job.get("job_id")))
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail="Import navbati to'lgan. Birozdan so'ng qayta urinib ko'ring.")

    queue_position = IMPORT_JOB_QUEUE.qsize()
    _touch_job(
        job,
        status="queued",
        phase="queued",
        queue_position=queue_position,
        message=f"Navbatga qo'shildi ({queue_position}-o'rin).",
    )
    return queue_position


async def startup_import_workers() -> None:
    await _ensure_import_workers()


async def shutdown_import_workers() -> None:
    global IMPORT_WORKER_TASKS, IMPORT_JOB_QUEUE
    tasks = [task for task in IMPORT_WORKER_TASKS if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    IMPORT_WORKER_TASKS.clear()
    IMPORT_JOB_QUEUE = None


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm_text(value: Any) -> str:
    raw = _s(value)
    if not raw:
        return ""
    return " ".join(raw.split()).casefold()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _cache_get(cache: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if cache is None:
        return None
    bucket = cache.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        cache[key] = bucket
    return bucket


def _cached_name_lookup(
    db: Session,
    model: Any,
    *,
    name: str,
    cache: dict[str, Any] | None,
    cache_key: str,
) -> Any | None:
    clean = _s(name)
    norm = _norm_text(clean)
    if not clean or not norm:
        return None

    bucket = _cache_get(cache, cache_key)
    if bucket is not None and not bucket.get("__loaded__"):
        for row_id, row_name in db.query(model.id, model.name).all():
            row_norm = _norm_text(row_name)
            if row_norm and row_norm not in bucket:
                bucket[row_norm] = row_id
        bucket["__loaded__"] = True

    if bucket is not None:
        row_id = bucket.get(norm)
        if isinstance(row_id, int) and row_id > 0:
            found = db.query(model).filter(model.id == row_id).first()
            if found:
                return found
            bucket.pop(norm, None)

    exact = db.query(model).filter(model.name == clean).first()
    if exact and bucket is not None:
        bucket[norm] = exact.id
    return exact


def _cached_name_store(
    cache: dict[str, Any] | None,
    cache_key: str,
    *,
    name: str,
    row_id: int,
) -> None:
    bucket = _cache_get(cache, cache_key)
    norm = _norm_text(name)
    if bucket is not None and norm and row_id > 0:
        bucket[norm] = row_id


def _book_cache_load(
    db: Session,
    model: Any,
    *,
    cache: dict[str, Any] | None,
    cache_key: str,
) -> dict[str, Any] | None:
    bucket = _cache_get(cache, cache_key)
    if bucket is None:
        return None
    if bucket.get("__loaded__"):
        return bucket

    for row_id, row_title, row_isbn, row_language in db.query(model.id, model.title, model.isbn, model.language).all():
        title_norm = _norm_text(row_title)
        lang_norm = _norm_text(row_language)
        isbn_norm = _norm_text(row_isbn)
        if title_norm:
            bucket[f"tl:{title_norm}|{lang_norm}"] = row_id
            bucket[f"tl:{title_norm}|"] = row_id
        if isbn_norm:
            bucket[f"isbn:{isbn_norm}"] = row_id
    bucket["__loaded__"] = True
    return bucket


def _book_cache_store(
    cache: dict[str, Any] | None,
    cache_key: str,
    *,
    row_id: int,
    title: Any,
    isbn: Any,
    language: Any,
) -> None:
    bucket = _cache_get(cache, cache_key)
    if bucket is None or row_id <= 0:
        return

    title_norm = _norm_text(title)
    lang_norm = _norm_text(language)
    isbn_norm = _norm_text(isbn)
    if title_norm:
        bucket[f"tl:{title_norm}|{lang_norm}"] = row_id
        bucket[f"tl:{title_norm}|"] = row_id
    if isbn_norm:
        bucket[f"isbn:{isbn_norm}"] = row_id


def _infer_payload_type(item: dict[str, Any], preferred: str | None = None) -> str:
    p = _s(preferred).lower()
    
    scope = _s(item.get("scope")).lower()
    if "online" in scope:
        return "online"
    if "offline" in scope or "printed" in scope:
        return "printed"

    if isinstance(item.get("online_book"), dict):
        return "online"

    has_editions = bool(item.get("editions"))
    has_copies = bool(item.get("copies"))
    
    book_dict = item.get("book")
    if isinstance(book_dict, dict):
        has_editions = has_editions or bool(book_dict.get("editions"))
        has_copies = has_copies or bool(book_dict.get("copies"))

    if has_editions and not has_copies:
        return "online"
    if has_copies and not has_editions:
        return "printed"

    if p in {"printed", "online"}:
        return p

    return "printed"


def _guess_extension(url: str, content_type: str | None = None) -> str:
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path or "")
    ext = os.path.splitext(path)[1].lower()
    if ext and len(ext) <= 10:
        return ext
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip().lower()) or ""
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed:
            return guessed
    return ".bin"


def _media_candidates(source_origin: str, *values: Any) -> list[str]:
    candidates: list[str] = []

    def add_one(raw: str):
        raw = _s(raw)
        if not raw or raw.lower().startswith("data:"):
            return

        if raw.startswith(("http://", "https://")):
            abs_url = raw
        elif raw.startswith("//"):
            scheme = urllib.parse.urlsplit(source_origin).scheme or "https"
            abs_url = f"{scheme}:{raw}"
        else:
            if not source_origin:
                return
            abs_url = urllib.parse.urljoin(source_origin.rstrip("/") + "/", raw)

        if abs_url not in candidates:
            candidates.append(abs_url)

    for value in values:
        if isinstance(value, dict):
            add_one(value.get("url", ""))
            add_one(value.get("path", ""))
            continue

        text = _s(value)
        add_one(text)

        # Ko'pincha API "book_covers/..." qaytaradi, haqiqiy URL esa "/media/book_covers/..."
        if text and not text.startswith(("http://", "https://", "//", "/media/", "media/", "/")):
            add_one("/media/" + text)
        if text.startswith("media/"):
            add_one("/" + text)

    return candidates


async def _download_to_static(
    client: httpx.AsyncClient,
    candidate_urls: list[str],
    target_dir: str,
    public_prefix: str,
) -> str | None:
    semaphore = _get_download_semaphore()
    for remote_url in candidate_urls:
        try:
            async with semaphore:
                async with client.stream("GET", remote_url, timeout=45.0) as response:
                    if response.status_code >= 400:
                        continue
                    ext = _guess_extension(remote_url, response.headers.get("content-type"))
                    filename = f"{uuid.uuid4().hex}{ext}"
                    destination = os.path.join(target_dir, filename)
                    with open(destination, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            if chunk:
                                f.write(chunk)
                    return f"{public_prefix}/{filename}"
        except Exception:
            continue
    return None


def _get_or_create_author_id(
    db: Session,
    author_payload: Any,
    user_id: int | None,
    lookup_cache: dict[str, Any] | None = None,
) -> int | None:
    payload = _as_dict(author_payload)
    clean_name = _s(payload.get("name") if payload else author_payload)
    clean_code = _s(payload.get("author_code"))
    clean_phone = _s(payload.get("phone_number"))
    clean_email = _s(payload.get("email"))
    clean_image = _s(payload.get("image"))

    if not clean_name and not clean_code:
        return None

    existing = None
    if clean_code:
        existing = db.query(Author).filter(Author.author_code == clean_code).first()

    if not existing and clean_name:
        existing = _cached_name_lookup(
            db,
            Author,
            name=clean_name,
            cache=lookup_cache,
            cache_key="authors",
        )

    if existing:
        changed = False
        if clean_name and not _s(existing.name):
            existing.name = clean_name
            changed = True
        if clean_code and not _s(existing.author_code):
            existing.author_code = clean_code
            changed = True
        if clean_phone and not _s(existing.phone_number):
            existing.phone_number = clean_phone
            changed = True
        if clean_email and not _s(existing.email):
            existing.email = clean_email
            changed = True
        if clean_image and not _s(existing.image):
            existing.image = clean_image
            changed = True
        if changed:
            db.flush()
        _cached_name_store(lookup_cache, "authors", name=existing.name, row_id=existing.id)
        return existing.id

    if not clean_name:
        clean_name = clean_code

    obj = Author(
        name=clean_name,
        phone_number=clean_phone or None,
        image=clean_image or None,
        email=clean_email or None,
        author_code=clean_code or None,
        is_active=True,
        added_by_id=user_id,
    )
    db.add(obj)
    db.flush()
    _cached_name_store(lookup_cache, "authors", name=obj.name, row_id=obj.id)
    return obj.id


def _get_or_create_book_type_id(
    db: Session,
    name: str,
    user_id: int | None,
    lookup_cache: dict[str, Any] | None = None,
) -> int | None:
    clean = _s(name)
    if not clean:
        return None

    existing = _cached_name_lookup(
        db,
        BookType,
        name=clean,
        cache=lookup_cache,
        cache_key="book_types",
    )
    if existing:
        return existing.id

    obj = BookType(name=clean, is_active=True, user_id=user_id)
    db.add(obj)
    db.flush()
    _cached_name_store(lookup_cache, "book_types", name=obj.name, row_id=obj.id)
    return obj.id


def _get_or_create_publisher_id(
    db: Session,
    name: str,
    user_id: int | None,
    lookup_cache: dict[str, Any] | None = None,
) -> int | None:
    clean = _s(name)
    if not clean:
        return None

    existing = _cached_name_lookup(
        db,
        Publisher,
        name=clean,
        cache=lookup_cache,
        cache_key="publishers",
    )
    if existing:
        return existing.id

    obj = Publisher(name=clean, is_active=True, user_id=user_id)
    db.add(obj)
    db.flush()
    _cached_name_store(lookup_cache, "publishers", name=obj.name, row_id=obj.id)
    return obj.id


def _get_or_create_city_id(
    db: Session,
    name: str,
    user_id: int | None,
    lookup_cache: dict[str, Any] | None = None,
) -> int | None:
    clean = _s(name)
    if not clean:
        return None

    existing = _cached_name_lookup(
        db,
        PublishedCity,
        name=clean,
        cache=lookup_cache,
        cache_key="published_cities",
    )
    if existing:
        return existing.id

    obj = PublishedCity(name=clean, is_active=True, user_id=user_id)
    db.add(obj)
    db.flush()
    _cached_name_store(lookup_cache, "published_cities", name=obj.name, row_id=obj.id)
    return obj.id


def _get_or_create_year_id(
    db: Session,
    year_value: Any,
    user_id: int | None,
    lookup_cache: dict[str, Any] | None = None,
) -> int | None:
    year = _to_int(year_value, 0)
    if year <= 0:
        return None

    year_cache = _cache_get(lookup_cache, "publication_years")
    if year_cache is not None:
        cached_id = year_cache.get(str(year))
        if isinstance(cached_id, int) and cached_id > 0:
            exists = db.query(PublicationYear.id).filter(PublicationYear.id == cached_id).first()
            if exists:
                return cached_id
            year_cache.pop(str(year), None)

    existing = db.query(PublicationYear).filter(PublicationYear.year == year).first()
    if existing:
        if year_cache is not None:
            year_cache[str(year)] = existing.id
        return existing.id

    obj = PublicationYear(year=year, is_active=True, user_id=user_id)
    db.add(obj)
    db.flush()
    if year_cache is not None:
        year_cache[str(year)] = obj.id
    return obj.id


def _get_or_create_bbk_id(
    db: Session,
    code: str,
    name: str,
    user_id: int | None,
    lookup_cache: dict[str, Any] | None = None,
) -> int | None:
    clean_code = _s(code)
    clean_name = _s(name)
    if not clean_code and not clean_name:
        return None

    bbk_code_cache = _cache_get(lookup_cache, "bbk_code")
    bbk_name_cache = _cache_get(lookup_cache, "bbk_name")
    if bbk_code_cache is not None and clean_code:
        cached_id = bbk_code_cache.get(clean_code)
        if isinstance(cached_id, int) and cached_id > 0:
            exists = db.query(BBK.id).filter(BBK.id == cached_id).first()
            if exists:
                return cached_id
            bbk_code_cache.pop(clean_code, None)
    if bbk_name_cache is not None and clean_name:
        name_norm = _norm_text(clean_name)
        cached_id = bbk_name_cache.get(name_norm)
        if isinstance(cached_id, int) and cached_id > 0:
            exists = db.query(BBK.id).filter(BBK.id == cached_id).first()
            if exists:
                return cached_id
            bbk_name_cache.pop(name_norm, None)

    existing = None
    if clean_code:
        existing = db.query(BBK).filter(BBK.code == clean_code).first()
    if not existing and clean_name:
        by_name = _cached_name_lookup(
            db,
            BBK,
            name=clean_name,
            cache=lookup_cache,
            cache_key="bbk_name",
        )
        existing = by_name
    if existing:
        if bbk_code_cache is not None and clean_code:
            bbk_code_cache[clean_code] = existing.id
        if bbk_name_cache is not None and clean_name:
            bbk_name_cache[_norm_text(clean_name)] = existing.id
        return existing.id

    obj = BBK(
        code=clean_code or "-",
        name=clean_name or clean_code or "Noma'lum BBK",
        is_active=True,
        user_id=user_id,
    )
    db.add(obj)
    db.flush()
    if bbk_code_cache is not None and _s(obj.code):
        bbk_code_cache[_s(obj.code)] = obj.id
    if bbk_name_cache is not None and _s(obj.name):
        bbk_name_cache[_norm_text(obj.name)] = obj.id
    return obj.id


def _pick_library_id_if_exists(db: Session, external_library_id: Any) -> int | None:
    lib_id = _to_int(external_library_id, 0)
    if lib_id <= 0:
        return None
    lib = db.query(Library).filter(Library.id == lib_id).first()
    return lib.id if lib else None


def _unique_inventory_number(base: str, used_numbers: set[str]) -> str:
    candidate = _s(base) or f"INV-{uuid.uuid4().hex[:8]}"
    if candidate not in used_numbers:
        used_numbers.add(candidate)
        return candidate

    suffix = 2
    while True:
        alt = f"{candidate}-{suffix}"
        if alt not in used_numbers:
            used_numbers.add(alt)
            return alt
        suffix += 1


def _unique_book_id_code(
    db: Session,
    raw_code: Any,
    used_codes: set[str],
    db_checked_codes: set[str],
) -> str | None:
    def exists_in_db(code: str) -> bool:
        if code in db_checked_codes:
            return code in used_codes
        db_checked_codes.add(code)
        exists = db.query(BookCopy.id).filter(BookCopy.book_id_code == code).first() is not None
        if exists:
            used_codes.add(code)
        return exists

    base = "".join(ch for ch in _s(raw_code) if ch.isdigit())[:9]
    if not base:
        base = ""
    if base and base not in used_codes and not exists_in_db(base):
        used_codes.add(base)
        return base

    while True:
        generated = f"{uuid.uuid4().int % 10**9:09d}"
        if generated in used_codes:
            continue
        if exists_in_db(generated):
            continue
        used_codes.add(generated)
        db_checked_codes.add(generated)
        return generated


def _chunked(values: list[str], size: int = 600) -> list[list[str]]:
    if not values:
        return []
    chunks: list[list[str]] = []
    step = max(size, 1)
    for idx in range(0, len(values), step):
        chunks.append(values[idx : idx + step])
    return chunks


def _prefetch_existing_copy_codes(db: Session, codes: set[str], copy_cache: dict[str, Any]) -> None:
    if not codes:
        return

    prepared = _prepare_copy_cache(db, copy_cache)
    cached_codes: set[str] = prepared["book_id_codes"]
    checked_codes: set[str] = prepared["db_checked_codes"]
    to_check = [code for code in codes if code and code not in checked_codes]
    if not to_check:
        return

    for chunk in _chunked(to_check):
        existing = db.query(BookCopy.book_id_code).filter(BookCopy.book_id_code.in_(chunk)).all()
        for row in existing:
            code = _s(row[0])
            if code:
                cached_codes.add(code)
    checked_codes.update(to_check)


def _prepare_copy_cache(db: Session, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    data = cache if isinstance(cache, dict) else {}
    inventory_numbers = data.get("inventory_numbers")
    if not isinstance(inventory_numbers, set):
        data["inventory_numbers"] = set()
    book_id_codes = data.get("book_id_codes")
    if not isinstance(book_id_codes, set):
        data["book_id_codes"] = set()
    db_checked_codes = data.get("db_checked_codes")
    if not isinstance(db_checked_codes, set):
        data["db_checked_codes"] = set()
    return data


def _extract_inventory_prefix(copies: list[dict[str, Any]], fallback: str = "") -> str:
    for copy in copies:
        inv = _s(copy.get("inventory_number"))
        if "/" in inv:
            return inv.rsplit("/", 1)[0]
    return _s(fallback)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = _s(value).lower()
    if text in {"1", "true", "yes", "y", "ha", "on"}:
        return True
    if text in {"0", "false", "no", "n", "yoq", "off"}:
        return False
    return default


def _find_existing_printed_book(
    db: Session,
    *,
    title: str,
    isbn: str | None,
    language: str | None,
    lookup_cache: dict[str, Any] | None = None,
) -> Book | None:
    clean_isbn = _s(isbn)
    clean_title = _s(title)
    clean_lang = _s(language).lower()
    title_norm = _norm_text(clean_title)
    lang_norm = _norm_text(clean_lang)

    bucket = _book_cache_load(db, Book, cache=lookup_cache, cache_key="printed_books")
    if bucket is not None:
        if clean_isbn:
            cached_id = bucket.get(f"isbn:{_norm_text(clean_isbn)}")
            if isinstance(cached_id, int) and cached_id > 0:
                found = db.query(Book).filter(Book.id == cached_id).first()
                if found:
                    return found
                bucket.pop(f"isbn:{_norm_text(clean_isbn)}", None)
        if title_norm:
            key = f"tl:{title_norm}|{lang_norm}"
            cached_id = bucket.get(key)
            if isinstance(cached_id, int) and cached_id > 0:
                found = db.query(Book).filter(Book.id == cached_id).first()
                if found:
                    return found
                bucket.pop(key, None)
            fallback_key = f"tl:{title_norm}|"
            if fallback_key != key:
                cached_id = bucket.get(fallback_key)
                if isinstance(cached_id, int) and cached_id > 0:
                    found = db.query(Book).filter(Book.id == cached_id).first()
                    if found:
                        return found
                    bucket.pop(fallback_key, None)

    if clean_isbn:
        book = db.query(Book).filter(Book.isbn == clean_isbn).order_by(Book.id.desc()).first()
        if book:
            _book_cache_store(
                lookup_cache,
                "printed_books",
                row_id=book.id,
                title=book.title,
                isbn=book.isbn,
                language=book.language,
            )
            return book

    if not clean_title:
        return None

    query = db.query(Book)
    if clean_lang:
        query = query.filter(Book.language == clean_lang)
    candidates = query.order_by(Book.id.desc()).all()
    for candidate in candidates:
        if _norm_text(candidate.title) == title_norm:
            _book_cache_store(
                lookup_cache,
                "printed_books",
                row_id=candidate.id,
                title=candidate.title,
                isbn=candidate.isbn,
                language=candidate.language,
            )
            return candidate
    if clean_lang:
        candidates = db.query(Book).order_by(Book.id.desc()).all()
        for candidate in candidates:
            if _norm_text(candidate.title) == title_norm:
                _book_cache_store(
                    lookup_cache,
                    "printed_books",
                    row_id=candidate.id,
                    title=candidate.title,
                    isbn=candidate.isbn,
                    language=candidate.language,
                )
                return candidate
    return None


def _find_existing_online_book(
    db: Session,
    *,
    title: str,
    isbn: str | None,
    language: str | None,
    external_id: str | None = None,
    lookup_cache: dict[str, Any] | None = None,
) -> OnlineBook | None:
    clean_isbn = _s(isbn)
    clean_title = _s(title)
    clean_lang = _s(language).lower()
    clean_ext_id = _s(external_id)
    title_norm = _norm_text(clean_title)
    lang_norm = _norm_text(clean_lang)

    # 1. Try external_id first (most reliable — unique per remote source)
    if clean_ext_id:
        ext_cache = _cache_get(lookup_cache, "online_books_ext")
        if ext_cache is not None:
            cached_id = ext_cache.get(clean_ext_id)
            if isinstance(cached_id, int) and cached_id > 0:
                found = db.query(OnlineBook).filter(OnlineBook.id == cached_id).first()
                if found:
                    return found
                ext_cache.pop(clean_ext_id, None)
        book = db.query(OnlineBook).filter(OnlineBook.external_id == clean_ext_id).first()
        if book:
            if ext_cache is not None:
                ext_cache[clean_ext_id] = book.id
            return book

    bucket = _book_cache_load(db, OnlineBook, cache=lookup_cache, cache_key="online_books")
    if bucket is not None:
        if clean_isbn:
            cached_id = bucket.get(f"isbn:{_norm_text(clean_isbn)}")
            if isinstance(cached_id, int) and cached_id > 0:
                found = db.query(OnlineBook).filter(OnlineBook.id == cached_id).first()
                if found:
                    return found
                bucket.pop(f"isbn:{_norm_text(clean_isbn)}", None)
        # Only use title-based cache when no external_id — otherwise wrong books get matched
        if title_norm and not clean_ext_id:
            key = f"tl:{title_norm}|{lang_norm}"
            cached_id = bucket.get(key)
            if isinstance(cached_id, int) and cached_id > 0:
                found = db.query(OnlineBook).filter(OnlineBook.id == cached_id).first()
                if found:
                    return found
                bucket.pop(key, None)
            fallback_key = f"tl:{title_norm}|"
            if fallback_key != key:
                cached_id = bucket.get(fallback_key)
                if isinstance(cached_id, int) and cached_id > 0:
                    found = db.query(OnlineBook).filter(OnlineBook.id == cached_id).first()
                    if found:
                        return found
                    bucket.pop(fallback_key, None)

    if clean_isbn:
        book = db.query(OnlineBook).filter(OnlineBook.isbn == clean_isbn).order_by(OnlineBook.id.desc()).first()
        if book:
            _book_cache_store(
                lookup_cache,
                "online_books",
                row_id=book.id,
                title=book.title,
                isbn=book.isbn,
                language=book.language,
            )
            return book

    # Only match by title if no external_id was provided (manual imports, not bulk remote)
    if not clean_ext_id and clean_title:
        query = db.query(OnlineBook)
        if clean_lang:
            query = query.filter(OnlineBook.language == clean_lang)
        candidates = query.order_by(OnlineBook.id.desc()).all()
        for candidate in candidates:
            if _norm_text(candidate.title) == title_norm:
                _book_cache_store(
                    lookup_cache,
                    "online_books",
                    row_id=candidate.id,
                    title=candidate.title,
                    isbn=candidate.isbn,
                    language=candidate.language,
                )
                return candidate
        if clean_lang:
            candidates = db.query(OnlineBook).order_by(OnlineBook.id.desc()).all()
            for candidate in candidates:
                if _norm_text(candidate.title) == title_norm:
                    _book_cache_store(
                        lookup_cache,
                        "online_books",
                        row_id=candidate.id,
                        title=candidate.title,
                        isbn=candidate.isbn,
                        language=candidate.language,
                    )
                    return candidate
    return None


def _build_paged_url(source_url: str, offset: int, limit: int, page_num: int = 0) -> str:
    parsed = urllib.parse.urlsplit(source_url)
    original_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for (k, v) in original_params if k.lower() not in {"offset", "limit", "page", "size"}]
    
    filtered.append(("offset", str(max(offset, 0))))
    filtered.append(("limit", str(max(limit, 1))))
    
    if page_num > 0:
        filtered.append(("page", str(page_num)))
    else:
        page = (offset // max(limit, 1)) + 1
        filtered.append(("page", str(page)))
        
    rebuilt_query = urllib.parse.urlencode(filtered, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, rebuilt_query, parsed.fragment))


def _payload_has_more(payload: dict[str, Any], offset: int, row_count: int) -> bool:
    has_more = payload.get("has_more")
    if isinstance(has_more, bool):
        return has_more

    current_page = _to_int(payload.get("current_page"), 0)
    last_page = _to_int(payload.get("last_page"), 0)
    if current_page > 0 and last_page > 0:
        return current_page < last_page

    total_books = _to_int(payload.get("total_books"), 0)
    if total_books > 0:
        return (offset + row_count) < total_books

    expected_limit = _to_int(payload.get("limit"), 0)
    return row_count > 0 and expected_limit > 0 and row_count >= expected_limit


async def _iter_remote_pages(
    client: httpx.AsyncClient,
    source_url: str,
    limit: int = 200,
    max_pages: int = 400,
):
    safe_limit = min(max(limit, 1), 500)
    offset = 0
    page_count = 0

    while True:
        if page_count >= max_pages:
            raise HTTPException(
                status_code=400,
                detail="Barcha kitoblarni olish limiti oshib ketdi. API javobida offset/has_more ni tekshiring.",
            )

        page_count += 1
        page_url = _build_paged_url(source_url, offset=offset, limit=safe_limit, page_num=page_count)
        response = await client.get(page_url, timeout=45.0)
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Tashqi API JSON obyekt qaytarmadi.")

        page_rows = [_as_dict(row) for row in _as_list(payload.get("books"))]
        if not page_rows:
            break

        yield payload, page_rows, offset, page_count

        if not _payload_has_more(payload, offset=offset, row_count=len(page_rows)):
            break

        suggested_next = _to_int(payload.get("next_offset"), -1)
        next_offset = suggested_next if suggested_next > offset else (offset + len(page_rows))
        if next_offset <= offset:
            break
        offset = next_offset


async def _fetch_all_remote_items(
    client: httpx.AsyncClient,
    source_url: str,
    limit: int = 200,
    max_pages: int = 400,
    progress_hook: Any | None = None,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    async for payload, page_rows, _offset, page_count in _iter_remote_pages(
        client=client,
        source_url=source_url,
        limit=limit,
        max_pages=max_pages,
    ):
        all_items.extend(page_rows)

        if progress_hook:
            try:
                progress_hook(payload=payload, loaded=len(all_items), page_count=page_count, page_size=len(page_rows))
            except Exception:
                pass

    return all_items


async def _import_printed_item(
    db: Session,
    client: httpx.AsyncClient,
    source_origin: str,
    raw_item: dict[str, Any],
    user_id: int | None,
    update_existing: bool = True,
    lookup_cache: dict[str, Any] | None = None,
    copy_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = _as_dict(raw_item)
    book_data = _as_dict(item.get("book")) or item
    related = _as_dict(item.get("related"))
    media = _as_dict(item.get("media"))

    title = _s(book_data.get("title"))
    if not title:
        raise HTTPException(status_code=422, detail="Tanlangan bosma kitobda title mavjud emas.")

    rel_book_type = _as_dict(related.get("book_type"))
    rel_bbk = _as_dict(related.get("bbk"))
    rel_publisher = _as_dict(related.get("publisher"))
    rel_city = _as_dict(related.get("published_city"))
    rel_year = _as_dict(related.get("publication_year"))

    book_type_id = _get_or_create_book_type_id(db, rel_book_type.get("name"), user_id, lookup_cache=lookup_cache)
    bbk_id = _get_or_create_bbk_id(db, rel_bbk.get("code"), rel_bbk.get("name"), user_id, lookup_cache=lookup_cache)
    publisher_id = _get_or_create_publisher_id(db, rel_publisher.get("name"), user_id, lookup_cache=lookup_cache)
    published_city_id = _get_or_create_city_id(db, rel_city.get("name"), user_id, lookup_cache=lookup_cache)
    publication_year_id = _get_or_create_year_id(db, rel_year.get("year"), user_id, lookup_cache=lookup_cache)

    source_copies = [_as_dict(c) for c in _as_list(item.get("copies"))]
    total_copies_source = _to_int(book_data.get("total_copies"), 0)
    if not source_copies and total_copies_source > 0:
        prefix = _s(book_data.get("total_inventory")) or "EXT"
        generated: list[dict[str, Any]] = []
        for idx in range(1, total_copies_source + 1):
            generated.append(
                {
                    "inventory_number": f"{prefix}/{idx}",
                    "status": "not_sended",
                    "have_status": "yes",
                    "is_print": False,
                }
            )
        source_copies = generated

    total_inventory = _extract_inventory_prefix(source_copies, fallback=_s(book_data.get("total_inventory")))
    total_copies = len(source_copies) if source_copies else max(total_copies_source, _to_int(book_data.get("quantity"), 0))
    language_code = (_s(book_data.get("language")).lower() or "uz")
    clean_isbn = _s(book_data.get("isbn")) or None

    image_path = item.get("__prefetched_image")
    file_path = item.get("__prefetched_file")

    existing_book = None
    if update_existing:
        existing_book = _find_existing_printed_book(
            db,
            title=title,
            isbn=clean_isbn,
            language=language_code,
            lookup_cache=lookup_cache,
        )
    is_update = existing_book is not None

    if is_update:
        book = existing_book
        book.title = title
        book.quantity = _to_int(book_data.get("quantity"), total_copies)
        book.adad = _to_int(book_data.get("adad"), 0)
        if image_path:
            book.image = image_path
        if file_path:
            book.file = file_path
        book.isbn = clean_isbn
        book.language = language_code
        book.annotation = _s(book_data.get("annotation")) or None
        book.pages = _to_int(book_data.get("pages"), 0) or None
        book.price = _to_float(book_data.get("price"), 0.0)
        book.total_inventory = total_inventory
        book.total_copies = total_copies
        book.added_by_id = user_id
        book.book_type_id = book_type_id
        book.bbk_id = bbk_id
        book.publication_year_id = publication_year_id
        book.publisher_id = publisher_id
        book.published_city_id = published_city_id
        db.flush()
    else:
        book = Book(
            title=title,
            quantity=_to_int(book_data.get("quantity"), total_copies),
            adad=_to_int(book_data.get("adad"), 0),
            image=image_path,
            isbn=clean_isbn,
            file=file_path,
            language=language_code,
            annotation=_s(book_data.get("annotation")) or None,
            pages=_to_int(book_data.get("pages"), 0) or None,
            price=_to_float(book_data.get("price"), 0.0),
            total_inventory=total_inventory,
            total_copies=total_copies,
            added_by_id=user_id,
            book_type_id=book_type_id,
            bbk_id=bbk_id,
            publication_year_id=publication_year_id,
            publisher_id=publisher_id,
            published_city_id=published_city_id,
        )
        db.add(book)
        db.flush()

    _book_cache_store(
        lookup_cache,
        "printed_books",
        row_id=book.id,
        title=book.title,
        isbn=book.isbn,
        language=book.language,
    )

    replaced_copies = 0
    if is_update:
        old_copy_rows = db.query(BookCopy.inventory_number, BookCopy.book_id_code).filter(
            BookCopy.original_book_id == book.id
        ).all()
        replaced_copies = len(old_copy_rows)
        db.query(BookCopy).filter(BookCopy.original_book_id == book.id).delete(synchronize_session=False)
        db.flush()
        if copy_cache is not None:
            copy_data_cache = _prepare_copy_cache(db, copy_cache)
            inv_set = copy_data_cache.get("inventory_numbers", set())
            code_set = copy_data_cache.get("book_id_codes", set())
            for inv_number, book_code in old_copy_rows:
                inv_set.discard(_s(inv_number))
                code_set.discard(_s(book_code))

    author_ids: list[int] = []
    for author in _as_list(item.get("authors")):
        a_id = _get_or_create_author_id(db, author, user_id, lookup_cache=lookup_cache)
        if a_id and a_id not in author_ids:
            author_ids.append(a_id)
    if author_ids:
        book.authors = db.query(Author).filter(Author.id.in_(author_ids)).all()
    else:
        book.authors = []

    prepared = _prepare_copy_cache(db, copy_cache if copy_cache is not None else {})
    existing_inv: set[str] = prepared["inventory_numbers"]
    existing_codes: set[str] = prepared["book_id_codes"]
    db_checked_codes: set[str] = prepared["db_checked_codes"]

    incoming_raw_codes = {
        "".join(ch for ch in _s(copy_item.get("book_id_code")) if ch.isdigit())[:9]
        for copy_item in source_copies
    }
    incoming_raw_codes = {code for code in incoming_raw_codes if code}
    _prefetch_existing_copy_codes(db, incoming_raw_codes, prepared)

    copy_rows: list[dict[str, Any]] = []
    now = datetime.utcnow()
    for copy_data in source_copies:
        status = "not_sended"

        have_status = _s(copy_data.get("have_status")) or "yes"
        if have_status not in VALID_COPY_HAVE_STATUSES:
            have_status = "yes"

        inv_number = _unique_inventory_number(_s(copy_data.get("inventory_number")), existing_inv)
        book_id_code = _unique_book_id_code(db, copy_data.get("book_id_code"), existing_codes, db_checked_codes)

        copy_rows.append(
            {
                "original_book_id": book.id,
                "inventory_number": inv_number,
                "book_id_code": book_id_code,
                "is_print": _to_bool(copy_data.get("is_print"), False),
                "id_card_printed": _to_bool(copy_data.get("id_card_printed"), False),
                "qr_printed": _to_bool(copy_data.get("qr_printed"), False),
                "status": status,
                "have_status": have_status,
                "library_id": _pick_library_id_if_exists(db, copy_data.get("library_id")),
                "created_at": now,
                "updated_at": now,
            }
        )

    created_copies = len(copy_rows)
    if copy_rows:
        db.bulk_insert_mappings(BookCopy, copy_rows)

    book.total_copies = created_copies
    if created_copies > 0:
        book.total_inventory = _extract_inventory_prefix(source_copies, fallback=total_inventory)
    else:
        book.total_inventory = total_inventory
    if book.quantity <= 0 and created_copies > 0:
        book.quantity = created_copies

    return {
        "imported_type": "printed",
        "book_id": book.id,
        "title": book.title,
        "updated": is_update,
        "created": not is_update,
        "created_copies": created_copies,
        "replaced_copies": replaced_copies,
        "image_saved": bool(book.image),
        "file_saved": bool(book.file),
        "redirect_url": f"/books/{book.id}",
        "message": "Bosma kitob to'liq yuklandi.",
    }


async def _import_online_item(
    db: Session,
    client: httpx.AsyncClient,
    source_origin: str,
    raw_item: dict[str, Any],
    user_id: int | None,
    update_existing: bool = True,
    lookup_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = _as_dict(raw_item)
    online_data = _as_dict(item.get("online_book")) or _as_dict(item.get("book")) or item
    related_root = _as_dict(item.get("related"))

    title = _s(online_data.get("title"))
    if not title:
        raise HTTPException(status_code=422, detail="Tanlangan online kitobda title mavjud emas.")

    # Extract remote server's ID to uniquely identify this book
    raw_ext_id = online_data.get("id")
    clean_ext_id = _s(raw_ext_id) if raw_ext_id is not None else None

    rel_book_type = _as_dict(related_root.get("book_type"))
    rel_bbk = _as_dict(related_root.get("bbk"))

    language_code = (_s(online_data.get("language")).lower() or "uz")
    clean_isbn = _s(online_data.get("isbn")) or None

    existing_book = None
    if update_existing:
        existing_book = _find_existing_online_book(
            db,
            title=title,
            isbn=clean_isbn,
            language=language_code,
            external_id=clean_ext_id,
            lookup_cache=lookup_cache,
        )
    is_update = existing_book is not None

    if is_update:
        online_book = existing_book
        online_book.title = title
        online_book.language = language_code
        online_book.isbn = clean_isbn
        if clean_ext_id and not _s(online_book.external_id):
            online_book.external_id = clean_ext_id
        online_book.annotation = _s(online_data.get("annotation")) or None
        online_book.library_id = _pick_library_id_if_exists(db, online_data.get("library_id"))
        online_book.added_by_id = user_id
        online_book.bbk_id = _get_or_create_bbk_id(
            db, rel_bbk.get("code"), rel_bbk.get("name"), user_id, lookup_cache=lookup_cache
        )
        online_book.book_type_id = _get_or_create_book_type_id(
            db, rel_book_type.get("name"), user_id, lookup_cache=lookup_cache
        )
        db.flush()
    else:
        online_book = OnlineBook(
            title=title,
            external_id=clean_ext_id or None,
            language=language_code,
            isbn=clean_isbn,
            annotation=_s(online_data.get("annotation")) or None,
            library_id=_pick_library_id_if_exists(db, online_data.get("library_id")),
            added_by_id=user_id,
            bbk_id=_get_or_create_bbk_id(
                db, rel_bbk.get("code"), rel_bbk.get("name"), user_id, lookup_cache=lookup_cache
            ),
            book_type_id=_get_or_create_book_type_id(
                db, rel_book_type.get("name"), user_id, lookup_cache=lookup_cache
            ),
        )
        db.add(online_book)
        db.flush()

    _book_cache_store(
        lookup_cache,
        "online_books",
        row_id=online_book.id,
        title=online_book.title,
        isbn=online_book.isbn,
        language=online_book.language,
    )

    author_ids: list[int] = []
    for author in _as_list(item.get("authors")):
        a_id = _get_or_create_author_id(db, author, user_id, lookup_cache=lookup_cache)
        if a_id and a_id not in author_ids:
            author_ids.append(a_id)
    if author_ids:
        online_book.authors = db.query(Author).filter(Author.id.in_(author_ids)).all()
    else:
        online_book.authors = []

    editions = _as_list(item.get("editions"))
    created_editions = 0
    saved_image_count = 0
    saved_file_count = 0
    saved_audio_count = 0
    replaced_editions = 0

    if is_update:
        replaced_editions = db.query(BookEdition).filter(BookEdition.book_id == online_book.id).count()
        db.query(BookEdition).filter(BookEdition.book_id == online_book.id).delete(synchronize_session=False)
        db.flush()

    edition_rows: list[dict[str, Any]] = []
    now = datetime.utcnow()
    for raw_edition in editions:
        wrapper = _as_dict(raw_edition)
        edition_data = _as_dict(wrapper.get("edition")) or wrapper
        media = _as_dict(wrapper.get("media"))
        related = _as_dict(wrapper.get("related"))

        rel_year = _as_dict(related.get("publication_year"))
        rel_publisher = _as_dict(related.get("publisher"))
        rel_city = _as_dict(related.get("published_city"))

        image_path = wrapper.get("__prefetched_image")
        file_path = wrapper.get("__prefetched_file")
        audio_path = wrapper.get("__prefetched_audio")

        status = _s(edition_data.get("status")) or "undistributed"
        if status not in VALID_EDITION_STATUSES:
            status = "undistributed"

        edition_rows.append(
            {
                "book_id": online_book.id,
                "pages": _to_int(edition_data.get("pages"), 0) or None,
                "adad": _to_int(edition_data.get("adad"), 0),
                "status": status,
                "image": image_path,
                "file": file_path,
                "audio_file": audio_path,
                "publication_year_id": _get_or_create_year_id(
                    db, rel_year.get("year"), user_id, lookup_cache=lookup_cache
                ),
                "publisher_id": _get_or_create_publisher_id(
                    db, rel_publisher.get("name"), user_id, lookup_cache=lookup_cache
                ),
                "published_city_id": _get_or_create_city_id(
                    db, rel_city.get("name"), user_id, lookup_cache=lookup_cache
                ),
                "created_at": now,
                "updated_at": now,
            }
        )
        if image_path:
            saved_image_count += 1
        if file_path:
            saved_file_count += 1
        if audio_path:
            saved_audio_count += 1

    if edition_rows:
        db.bulk_insert_mappings(BookEdition, edition_rows)
        created_editions = len(edition_rows)

    if not editions:
        db.add(BookEdition(book_id=online_book.id, status="undistributed", adad=0))
        created_editions = 1

    return {
        "imported_type": "online",
        "book_id": online_book.id,
        "title": online_book.title,
        "updated": is_update,
        "created": not is_update,
        "created_editions": created_editions,
        "replaced_editions": replaced_editions,
        "saved_images": saved_image_count,
        "saved_files": saved_file_count,
        "saved_audios": saved_audio_count,
        "redirect_url": f"/online-books/{online_book.id}",
        "message": "Online kitob to'liq yuklandi.",
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def external_books_index(request: Request, db: Session = Depends(get_db)):
    session_user = get_session_user(request)
    if not session_user:
        return RedirectResponse(url="/two_login", status_code=302)

    if not can_access_menu(session_user, "external_books"):
        return RedirectResponse(url=build_menu_denied_url(session_user, "external_books"), status_code=302)

    return templates.TemplateResponse(
        "external_books/index.html",
        _base_ctx(request, title="Tashqi Baza", active_menu="external_books"),
    )


@router.get("/api/fetch")
async def fetch_external_books(url: str, request: Request):
    """
    CORS muammolarini chetlab o'tish uchun server-side proxy.
    """
    _ensure_access(request)
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=35.0)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Target API returned error: {exc.response.text}",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/import")
async def import_external_book(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    session_user = _ensure_access(request)
    source_url = _s(payload.get("source_url"))
    selected_type = _s(payload.get("book_type") or payload.get("bookType") or payload.get("external_type"))
    # External import now works in "insert-only" mode: existing records are not updated.
    update_existing = False
    import_all = _to_bool(payload.get("import_all") if "import_all" in payload else payload.get("importAll"), False)
    fetch_limit = min(max(_to_int(payload.get("limit"), 200), 1), 500)
    max_pages = min(max(_to_int(payload.get("max_pages"), 400), 1), 2000)
    commit_every = min(max(_to_int(payload.get("commit_every"), 100), 1), 500)
    user_id = _to_int(session_user.get("id"), 0) or None

    single_item = _as_dict(payload.get("item"))
    incoming_items = [_as_dict(row) for row in _as_list(payload.get("items"))]
    if single_item and not incoming_items:
        incoming_items = [single_item]

    source_origin = ""
    if source_url:
        try:
            parsed = urllib.parse.urlsplit(source_url)
            source_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        except Exception:
            source_origin = ""

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if import_all:
                if not source_url:
                    raise HTTPException(status_code=422, detail="Barchasini yuklash uchun source_url yuborilishi kerak.")
                
                incoming_items = await _fetch_all_remote_items(
                    client=client,
                    source_url=source_url,
                    limit=fetch_limit,
                    max_pages=max_pages,
                )

            if not incoming_items:
                raise HTTPException(status_code=422, detail="Saqlash uchun kitob ma'lumoti yuborilmadi.")

            # ---------------- PREFETCH MEDIA METADATA ----------------
            async def _prefetch_printed(c_item):
                c_book = _as_dict(c_item.get("book")) or c_item
                c_media = _as_dict(c_item.get("media"))
                i_cand = _media_candidates(source_origin, _as_dict(c_media.get("image")), c_book.get("image"))
                f_cand = _media_candidates(source_origin, _as_dict(c_media.get("file")), c_book.get("file"))
                i_p, f_p = await asyncio.gather(
                    _download_to_static(client, i_cand, PRINTED_IMG_DIR, "/static/uploads/books/images"),
                    _download_to_static(client, f_cand, PRINTED_FILE_DIR, "/static/uploads/books/files"),
                )
                c_item["__prefetched_image"] = i_p
                c_item["__prefetched_file"] = f_p

            async def _prefetch_online(c_item):
                c_eds = _as_list(c_item.get("editions"))
                if not c_eds:
                    return
                async def _ed_fetch(ed_w_raw):
                    ed_w = _as_dict(ed_w_raw)
                    ed_data = _as_dict(ed_w.get("edition")) or ed_w
                    ed_m = _as_dict(ed_w.get("media"))
                    i_c = _media_candidates(source_origin, _as_dict(ed_m.get("image")), ed_data.get("image"))
                    f_c = _media_candidates(source_origin, _as_dict(ed_m.get("file")), ed_data.get("file"))
                    a_c = _media_candidates(source_origin, _as_dict(ed_m.get("audio_file")), ed_data.get("audio_file"))
                    i_p, f_p, a_p = await asyncio.gather(
                        _download_to_static(client, i_c, ONLINE_IMG_DIR, "/static/uploads/online_books/images"),
                        _download_to_static(client, f_c, ONLINE_FILE_DIR, "/static/uploads/online_books/files"),
                        _download_to_static(client, a_c, ONLINE_AUDIO_DIR, "/static/uploads/online_books/audio"),
                    )
                    ed_w["__prefetched_image"] = i_p
                    ed_w["__prefetched_file"] = f_p
                    ed_w["__prefetched_audio"] = a_p
                await asyncio.gather(*(_ed_fetch(e) for e in c_eds))

            prefetch_sem = asyncio.Semaphore(15)
            async def _bound_prefetch(ri):
                async with prefetch_sem:
                    it = _as_dict(ri)
                    i_type = _infer_payload_type(it, selected_type)
                    if i_type == "online":
                        await _prefetch_online(it)
                    else:
                        await _prefetch_printed(it)
            
            # Run all downloads in parallel heavily before hitting DB
            await asyncio.gather(*(_bound_prefetch(ri) for ri in incoming_items))
            # ---------------------------------------------------------

            results: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            lookup_cache: dict[str, Any] = {}
            copy_cache: dict[str, Any] = {"loaded": False}
            success_since_commit = 0

            for index, raw_item in enumerate(incoming_items):
                item = _as_dict(raw_item)
                if not item:
                    errors.append({"index": index, "message": "Noto'g'ri item format."})
                    continue

                item_type = _infer_payload_type(item, selected_type)
                try:
                    with db.begin_nested():
                        if item_type == "online":
                            result = await _import_online_item(
                                db=db,
                                client=client,
                                source_origin=source_origin,
                                raw_item=item,
                                user_id=user_id,
                                update_existing=update_existing,
                                lookup_cache=lookup_cache,
                            )
                        else:
                            result = await _import_printed_item(
                                db=db,
                                client=client,
                                source_origin=source_origin,
                                raw_item=item,
                                user_id=user_id,
                                update_existing=update_existing,
                                lookup_cache=lookup_cache,
                                copy_cache=copy_cache,
                            )
                    results.append(result)
                    success_since_commit += 1
                    if success_since_commit >= commit_every:
                        db.commit()
                        success_since_commit = 0
                    await asyncio.sleep(0)
                except HTTPException as exc:
                    lookup_cache.clear()
                    errors.append({"index": index, "message": str(exc.detail)})
                except Exception as exc:
                    lookup_cache.clear()
                    errors.append({"index": index, "message": str(exc)})

            if not results:
                detail = errors[0]["message"] if errors else "Import uchun mos kitob topilmadi."
                raise HTTPException(status_code=400, detail=f"Import xatosi: {detail}")
            if success_since_commit > 0:
                db.commit()

        saved_count = len(results)
        updated_count = sum(1 for row in results if _to_bool(row.get("updated"), False))
        created_count = saved_count - updated_count
        printed_count = sum(1 for row in results if row.get("imported_type") == "printed")
        online_count = sum(1 for row in results if row.get("imported_type") == "online")
        failed_count = len(errors)
        redirect_url = _s(results[0].get("redirect_url"))

        if saved_count == 1 and failed_count == 0 and not import_all and len(incoming_items) == 1:
            first = results[0]
            return {
                "ok": True,
                **first,
                "saved_count": saved_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "failed_count": failed_count,
            }

        summary = f"Jami {saved_count} ta kitob to'liq yuklandi (Bosma: {printed_count}, Online: {online_count})."
        if failed_count > 0:
            summary += f" {failed_count} ta elementda xatolik bo'ldi."

        return {
            "ok": True,
            "message": summary,
            "saved_count": saved_count,
            "created_count": created_count,
            "updated_count": updated_count,
            "failed_count": failed_count,
            "printed_count": printed_count,
            "online_count": online_count,
            "redirect_url": redirect_url,
            "results": results[:20],
            "errors": errors[:20],
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Import xatosi: {str(exc)}")


async def _run_import_job(job_id: str) -> None:
    job = IMPORT_JOBS.get(job_id)
    if not job:
        return

    payload = _as_dict(job.get("payload"))
    job["payload"] = {}
    source_url = _s(payload.get("source_url"))
    selected_type = _s(payload.get("book_type") or payload.get("bookType") or payload.get("external_type"))
    # External import now works in "insert-only" mode: existing records are not updated.
    update_existing = False
    import_all = _to_bool(payload.get("import_all") if "import_all" in payload else payload.get("importAll"), False)
    fetch_limit = min(max(_to_int(payload.get("limit"), 200), 1), 500)
    max_pages = min(max(_to_int(payload.get("max_pages"), 400), 1), 2000)
    commit_every = min(max(_to_int(payload.get("commit_every"), 100), 1), 500)
    user_id = _to_int(job.get("user_id"), 0) or None

    single_item = _as_dict(payload.get("item"))
    incoming_items = [_as_dict(row) for row in _as_list(payload.get("items"))]
    if single_item and not incoming_items:
        incoming_items = [single_item]

    source_origin = ""
    if source_url:
        try:
            parsed = urllib.parse.urlsplit(source_url)
            source_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        except Exception:
            source_origin = ""

    _touch_job(
        job,
        status="running",
        phase="prepare",
        queue_position=0,
        progress_percent=1,
        message="Import boshlandi.",
    )

    db = SessionLocal()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
            timeout=httpx.Timeout(45.0, connect=15.0),
        ) as client:
            results: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []

            async def _prefetch_printed(c_item):
                c_book = _as_dict(c_item.get("book")) or c_item
                c_media = _as_dict(c_item.get("media"))
                i_cand = _media_candidates(source_origin, _as_dict(c_media.get("image")), c_book.get("image"))
                f_cand = _media_candidates(source_origin, _as_dict(c_media.get("file")), c_book.get("file"))
                i_p, f_p = await asyncio.gather(
                    _download_to_static(client, i_cand, PRINTED_IMG_DIR, "/static/uploads/books/images"),
                    _download_to_static(client, f_cand, PRINTED_FILE_DIR, "/static/uploads/books/files"),
                )
                c_item["__prefetched_image"] = i_p
                c_item["__prefetched_file"] = f_p

            async def _prefetch_online(c_item):
                c_eds = _as_list(c_item.get("editions"))
                if not c_eds:
                    return
                async def _ed_fetch(ed_w_raw):
                    ed_w = _as_dict(ed_w_raw)
                    ed_data = _as_dict(ed_w.get("edition")) or ed_w
                    ed_m = _as_dict(ed_w.get("media"))
                    i_c = _media_candidates(source_origin, _as_dict(ed_m.get("image")), ed_data.get("image"))
                    f_c = _media_candidates(source_origin, _as_dict(ed_m.get("file")), ed_data.get("file"))
                    a_c = _media_candidates(source_origin, _as_dict(ed_m.get("audio_file")), ed_data.get("audio_file"))
                    i_p, f_p, a_p = await asyncio.gather(
                        _download_to_static(client, i_c, ONLINE_IMG_DIR, "/static/uploads/online_books/images"),
                        _download_to_static(client, f_c, ONLINE_FILE_DIR, "/static/uploads/online_books/files"),
                        _download_to_static(client, a_c, ONLINE_AUDIO_DIR, "/static/uploads/online_books/audio"),
                    )
                    ed_w["__prefetched_image"] = i_p
                    ed_w["__prefetched_file"] = f_p
                    ed_w["__prefetched_audio"] = a_p
                await asyncio.gather(*(_ed_fetch(e) for e in c_eds))

            async def _process_batch(items_batch: list[dict[str, Any]], total_processed: int, expected_total: int, phase_base: int):
                prefetch_sem = asyncio.Semaphore(15)
                __pf_done = [0]
                batch_size = len(items_batch)
                
                async def _bound_prefetch(ri):
                    async with prefetch_sem:
                        it = _as_dict(ri)
                        i_type = _infer_payload_type(it, selected_type)
                        if i_type == "online":
                            await _prefetch_online(it)
                        else:
                            await _prefetch_printed(it)
                        
                        __pf_done[0] += 1
                        if __pf_done[0] % 10 == 0:
                            current_total = total_processed + __pf_done[0]
                            pr_pct = phase_base + int((current_total / (expected_total or 1)) * 15)
                            _touch_job(
                                job, phase="fetching", progress_percent=min(99, pr_pct), processed=current_total, total=expected_total,
                                message=f"Fayllar yuklanmoqda ({__pf_done[0]}/{batch_size}) ... Umumiy: {current_total}/{expected_total}",
                            )

                await asyncio.gather(*(_bound_prefetch(ri) for ri in items_batch))

                lookup_cache: dict[str, Any] = {}
                copy_cache: dict[str, Any] = {"loaded": False}
                success_since_commit = 0
                
                for idx_in_batch, raw_item in enumerate(items_batch):
                    item = _as_dict(raw_item)
                    current_idx = total_processed + idx_in_batch + 1
                    
                    if not item:
                        errors.append({"index": current_idx, "message": "Noto'g'ri item format."})
                        continue

                    item_type = _infer_payload_type(item, selected_type)
                    try:
                        with db.begin_nested():
                            if item_type == "online":
                                result = await _import_online_item(
                                    db=db, client=client, source_origin=source_origin, raw_item=item,
                                    user_id=user_id, update_existing=update_existing, lookup_cache=lookup_cache,
                                )
                            else:
                                result = await _import_printed_item(
                                    db=db, client=client, source_origin=source_origin, raw_item=item,
                                    user_id=user_id, update_existing=update_existing, lookup_cache=lookup_cache, copy_cache=copy_cache,
                                )
                        results.append(result)
                        success_since_commit += 1
                        if success_since_commit >= commit_every:
                            db.commit()
                            success_since_commit = 0
                    except HTTPException as exc:
                        lookup_cache.clear()
                        errors.append({"index": current_idx, "message": str(exc.detail)})
                    except Exception as exc:
                        lookup_cache.clear()
                        errors.append({"index": current_idx, "message": str(exc)})

                    await asyncio.sleep(0)
                    
                    if current_idx % 10 == 0 or current_idx == expected_total:
                        pr_pct = phase_base + 15 + int((current_idx / (expected_total or 1)) * 35)
                        _touch_job(
                            job, phase="importing", progress_percent=min(99, pr_pct), processed=current_idx, total=expected_total,
                            message=f"Baza xotirasiga saqlanmoqda: {current_idx}/{expected_total}",
                        )
                
                if success_since_commit > 0:
                    db.commit()
                db.expunge_all()

            if import_all:
                if not source_url:
                    raise HTTPException(status_code=422, detail="Barchasini yuklash uchun source_url yuborilishi kerak.")

                total_processed = 0
                expected_total = 0

                async for payload, page_rows, offset, page_count in _iter_remote_pages(
                    client=client, source_url=source_url, limit=fetch_limit, max_pages=max_pages
                ):
                    if not page_rows:
                        continue
                    if page_count == 1:
                        expected_total = _to_int(payload.get("total_books"), 0)
                        if expected_total == 0:
                            expected_total = len(page_rows)
                    else:
                        if expected_total < total_processed + len(page_rows):
                            expected_total = total_processed + len(page_rows)

                    pr_pct = min(50, int((total_processed / (expected_total or 1)) * 50))
                    _touch_job(
                        job, phase="fetching", progress_percent=pr_pct, processed=total_processed, total=expected_total,
                        message=f"Tashqi serverdan sahifa olinmoqda: {total_processed}/{expected_total}",
                    )

                    await _process_batch(page_rows, total_processed, expected_total, phase_base=pr_pct)
                    total_processed += len(page_rows)
                    
                if not results and not errors:
                    raise HTTPException(status_code=422, detail="Saqlash uchun tashqi serverdan qaytgan ro'yxat bo'sh.")

            else:
                if not incoming_items:
                    raise HTTPException(status_code=422, detail="Saqlash uchun kitob ma'lumoti yuborilmadi.")
                
                expected_total = len(incoming_items)
                await _process_batch(incoming_items, total_processed=0, expected_total=expected_total, phase_base=0)
                
                if not results and not errors:
                    detail = errors[0]["message"] if errors else "Import uchun mos kitob topilmadi."
                    raise HTTPException(status_code=400, detail=f"Import xatosi: {detail}")

        saved_count = len(results)
        updated_count = sum(1 for row in results if _to_bool(row.get("updated"), False))
        created_count = saved_count - updated_count
        printed_count = sum(1 for row in results if row.get("imported_type") == "printed")
        online_count = sum(1 for row in results if row.get("imported_type") == "online")
        failed_count = len(errors)
        redirect_url = _s(results[0].get("redirect_url"))

        summary = f"Jami {saved_count} ta kitob to'liq yuklandi (Bosma: {printed_count}, Online: {online_count})."
        if failed_count > 0:
            summary += f" {failed_count} ta elementda xatolik bo'ldi."

        result_payload = {
            "ok": True,
            "message": summary,
            "saved_count": saved_count,
            "created_count": created_count,
            "updated_count": updated_count,
            "failed_count": failed_count,
            "printed_count": printed_count,
            "online_count": online_count,
            "redirect_url": redirect_url,
            "results": results[:20],
            "errors": errors[:20],
        }
        _touch_job(
            job,
            status="done",
            phase="done",
            progress_percent=100,
            processed=_to_int(job.get("total"), _to_int(job.get("processed"), 0)),
            message=summary,
            result=result_payload,
            errors=errors[:20],
        )
    except HTTPException as exc:
        db.rollback()
        _touch_job(
            job,
            status="error",
            phase="error",
            progress_percent=max(1, _to_int(job.get("progress_percent"), 0)),
            message=str(exc.detail),
            errors=[{"message": str(exc.detail)}],
        )
    except Exception as exc:
        db.rollback()
        _touch_job(
            job,
            status="error",
            phase="error",
            progress_percent=max(1, _to_int(job.get("progress_percent"), 0)),
            message=f"Import xatosi: {str(exc)}",
            errors=[{"message": str(exc)}],
        )
    finally:
        db.close()


@router.post("/api/import-async")
async def start_import_external_books_async(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    session_user = _ensure_access(request)
    user_id = _to_int(session_user.get("id"), 0) or None
    job = _create_import_job(user_id=user_id, payload=payload)
    queue_position = await _enqueue_import_job(job)
    return {
        "ok": True,
        "job_id": job["job_id"],
        "queue_position": queue_position,
        "worker_count": IMPORT_WORKER_COUNT,
        **_job_public_data(job),
    }


@router.get("/api/import-progress/{job_id}")
async def get_import_external_books_progress(job_id: str, request: Request):
    session_user = _ensure_access(request)
    user_id = _to_int(session_user.get("id"), 0) or None
    job = IMPORT_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import jarayoni topilmadi.")

    job_user_id = _to_int(job.get("user_id"), 0) or None
    if job_user_id and user_id and job_user_id != user_id:
        raise HTTPException(status_code=403, detail="Ushbu import jarayoniga kirish taqiqlangan.")

    if _s(job.get("status")).lower() == "queued" and IMPORT_JOB_QUEUE is not None:
        try:
            queue_ids = list(IMPORT_JOB_QUEUE._queue)  # type: ignore[attr-defined]
            queue_position = queue_ids.index(job_id) + 1 if job_id in queue_ids else 0
            if queue_position != _to_int(job.get("queue_position"), 0):
                _touch_job(
                    job,
                    queue_position=queue_position,
                    message=f"Navbatda kutmoqda ({queue_position}-o'rin)." if queue_position > 0 else "Ishga tushmoqda.",
                )
        except Exception:
            pass

    return {"ok": True, **_job_public_data(job)}


@router.get("/api/import-progress-current")
async def get_current_import_external_books_progress(request: Request):
    session_user = _ensure_access(request)
    user_id = _to_int(session_user.get("id"), 0) or None
    job = _find_latest_user_job(user_id, include_finished=True)

    if not job:
        return {"ok": True, "has_job": False}

    status = _s(job.get("status")).lower()
    if status == "queued" and IMPORT_JOB_QUEUE is not None:
        try:
            queue_ids = list(IMPORT_JOB_QUEUE._queue)  # type: ignore[attr-defined]
            job_id = _s(job.get("job_id"))
            queue_position = queue_ids.index(job_id) + 1 if job_id in queue_ids else 0
            if queue_position != _to_int(job.get("queue_position"), 0):
                _touch_job(
                    job,
                    queue_position=queue_position,
                    message=f"Navbatda kutmoqda ({queue_position}-o'rin)." if queue_position > 0 else "Ishga tushmoqda.",
                )
        except Exception:
            pass

    return {"ok": True, "has_job": True, **_job_public_data(job)}
