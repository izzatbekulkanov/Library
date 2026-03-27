from __future__ import annotations

import html
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from app.core.i18n import I18nJinja2Templates as Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import build_menu_denied_url, can_access_menu, get_session_user
from app.core.database import get_db
from app.models.library import Book, BookCopy, BookType, OnlineBook

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

LANGUAGE_GROUPS: tuple[tuple[str, str], ...] = (
    ("uz_latin", "O'zbek tili (lotin)"),
    ("uz_cyril", "O'zbek tili (kiril)"),
    ("ru", "Rus tili"),
    ("en", "Ingliz tili"),
    ("other", "Boshqa tillar"),
)


def _guard(request: Request, menu_key: str = "reports"):
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


def _language_bucket(code: str | None) -> str:
    lang = str(code or "").strip().lower()
    if lang in {"uz", "uz-latn", "uz_latn"}:
        return "uz_latin"
    if lang in {"oz", "uz-cyr", "uz-cyrl", "uz_cyril", "uz-kiril"}:
        return "uz_cyril"
    if lang == "ru":
        return "ru"
    if lang == "en":
        return "en"
    return "other"


def _new_print_cells() -> dict[str, dict]:
    return {
        key: {"key": key, "label": label, "nomda": 0, "sonda": 0}
        for key, label in LANGUAGE_GROUPS
    }


def _new_online_cells() -> dict[str, dict]:
    return {
        key: {"key": key, "label": label, "count": 0}
        for key, label in LANGUAGE_GROUPS
    }


def _collect_type_map(db: Session) -> tuple[list[str], dict[int, str]]:
    ordered_names: list[str] = []
    by_id: dict[int, str] = {}
    rows = db.query(BookType.id, BookType.name).order_by(BookType.name.asc()).all()
    for type_id, type_name in rows:
        clean = (type_name or "").strip()
        if not clean:
            continue
        by_id[type_id] = clean
        if clean not in ordered_names:
            ordered_names.append(clean)
    return ordered_names, by_id


def _build_printed_report(db: Session) -> dict:
    ordered_type_names, type_name_by_id = _collect_type_map(db)
    rows_by_type: dict[str, dict] = {}

    for name in ordered_type_names:
        rows_by_type[name] = {"type_name": name, "cells": _new_print_cells()}

    rows = (
        db.query(
            Book.id,
            Book.language,
            Book.book_type_id,
            func.count(BookCopy.id).label("copies_count"),
        )
        .join(BookCopy, BookCopy.original_book_id == Book.id)
        .group_by(Book.id, Book.language, Book.book_type_id)
        .all()
    )
    for _, language, book_type_id, copies_count in rows:
        type_name = type_name_by_id.get(book_type_id) or "Noma'lum turi"
        if type_name not in rows_by_type:
            rows_by_type[type_name] = {"type_name": type_name, "cells": _new_print_cells()}
            ordered_type_names.append(type_name)

        bucket = _language_bucket(language)
        sonda = int(copies_count or 0)
        rows_by_type[type_name]["cells"][bucket]["nomda"] += 1
        rows_by_type[type_name]["cells"][bucket]["sonda"] += sonda

    totals = _new_print_cells()
    result_rows: list[dict] = []
    for idx, type_name in enumerate(ordered_type_names, start=1):
        row = rows_by_type[type_name]
        cells: list[dict] = []
        jami_nomda = 0
        jami_sonda = 0
        for key, label in LANGUAGE_GROUPS:
            cell = row["cells"][key]
            nomda = int(cell["nomda"])
            sonda = int(cell["sonda"])
            cells.append({"key": key, "label": label, "nomda": nomda, "sonda": sonda})
            jami_nomda += nomda
            jami_sonda += sonda
            totals[key]["nomda"] += nomda
            totals[key]["sonda"] += sonda

        result_rows.append(
            {
                "index": idx,
                "type_name": type_name,
                "cells": cells,
                "jami_nomda": jami_nomda,
                "jami_sonda": jami_sonda,
            }
        )

    total_cells: list[dict] = []
    total_jami_nomda = 0
    total_jami_sonda = 0
    for key, label in LANGUAGE_GROUPS:
        nomda = int(totals[key]["nomda"])
        sonda = int(totals[key]["sonda"])
        total_cells.append({"key": key, "label": label, "nomda": nomda, "sonda": sonda})
        total_jami_nomda += nomda
        total_jami_sonda += sonda

    return {
        "rows": result_rows,
        "totals": {
            "cells": total_cells,
            "jami_nomda": total_jami_nomda,
            "jami_sonda": total_jami_sonda,
        },
    }


def _build_online_report(db: Session) -> dict:
    ordered_type_names, type_name_by_id = _collect_type_map(db)
    rows_by_type: dict[str, dict] = {}
    for name in ordered_type_names:
        rows_by_type[name] = {"type_name": name, "cells": _new_online_cells()}

    books = db.query(OnlineBook.id, OnlineBook.language, OnlineBook.book_type_id).all()
    for _, language, book_type_id in books:
        type_name = type_name_by_id.get(book_type_id) or "Noma'lum turi"
        if type_name not in rows_by_type:
            rows_by_type[type_name] = {"type_name": type_name, "cells": _new_online_cells()}
            ordered_type_names.append(type_name)

        bucket = _language_bucket(language)
        rows_by_type[type_name]["cells"][bucket]["count"] += 1

    totals = _new_online_cells()
    result_rows: list[dict] = []
    for idx, type_name in enumerate(ordered_type_names, start=1):
        row = rows_by_type[type_name]
        cells: list[dict] = []
        jami = 0
        for key, label in LANGUAGE_GROUPS:
            count = int(row["cells"][key]["count"])
            cells.append({"key": key, "label": label, "count": count})
            jami += count
            totals[key]["count"] += count
        result_rows.append({"index": idx, "type_name": type_name, "cells": cells, "jami": jami})

    total_cells: list[dict] = []
    total_jami = 0
    for key, label in LANGUAGE_GROUPS:
        count = int(totals[key]["count"])
        total_cells.append({"key": key, "label": label, "count": count})
        total_jami += count

    return {
        "rows": result_rows,
        "totals": {"cells": total_cells, "jami": total_jami},
    }


def _word_response(filename: str, title: str, body_html: str) -> Response:
    doc = f"""<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    @page Section1 {{
      size: 841.89pt 595.28pt;
      mso-page-orientation: landscape;
      margin: 34pt 28pt 30pt 28pt;
    }}
    @page {{
      size: A4 landscape;
      margin: 12mm 10mm 10mm 10mm;
    }}
    html, body {{
      margin: 0;
      padding: 0;
      background: #ffffff;
      color: #000000;
      font-family: "Times New Roman", serif;
      font-size: 12pt;
    }}
    .a4-page {{
      width: 277mm;
      min-height: 188mm;
      margin: 0 auto;
      page: Section1;
      background: #ffffff;
      padding: 8pt 10pt 10pt 10pt;
      box-sizing: border-box;
    }}
    h2 {{
      margin: 0 0 10pt 0;
      text-align: center;
      font-size: 22pt;
      letter-spacing: 0.4px;
      color: #000000;
    }}
    p.meta {{
      margin: 0 0 10pt 0;
      text-align: right;
      font-size: 10pt;
      color: #333333;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      background: #ffffff;
    }}
    th, td {{
      border: 1px solid #000000;
      padding: 5px 5px;
      text-align: center;
      font-size: 12pt;
      line-height: 1.25;
      vertical-align: middle;
      color: #000000;
    }}
    th {{
      background: #f4f4f4;
      font-weight: 700;
      font-size: 10.5pt;
      color: #000000;
    }}
    td.left {{
      text-align: left;
    }}
    tr.total td {{
      font-weight: 700;
      background: #ececec;
    }}
    .sign {{
      margin-top: 7mm;
      font-size: 12.5pt;
      font-weight: 700;
      color: #000000;
    }}
  </style>
</head>
<body>
  <div class="a4-page">
    <h2>{html.escape(title)}</h2>
    <p class="meta">Yaratilgan vaqt: {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>
    {body_html}
  </div>
</body>
</html>"""
    return Response(
        content=doc,
        media_type="application/msword",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _printed_report_word_html(report: dict) -> str:
    group_header = "".join(f"<th colspan='2'>{html.escape(label)}</th>" for _, label in LANGUAGE_GROUPS)
    sub_header = "".join("<th>NOMDA</th><th>SONDA</th>" for _ in LANGUAGE_GROUPS)

    body_rows: list[str] = []
    for row in report["rows"]:
        cells = "".join(
            f"<td>{cell['nomda']}</td><td>{cell['sonda']}</td>"
            for cell in row["cells"]
        )
        body_rows.append(
            f"<tr>"
            f"<td>{row['index']}</td>"
            f"<td class='left'>{html.escape(row['type_name'])}</td>"
            f"{cells}"
            f"<td>{row['jami_nomda']}</td>"
            f"<td>{row['jami_sonda']}</td>"
            f"</tr>"
        )

    if not body_rows:
        colspan = 2 + (len(LANGUAGE_GROUPS) * 2) + 2
        body_rows.append(f"<tr><td colspan='{colspan}'>Ma'lumot topilmadi.</td></tr>")

    totals_cells = "".join(
        f"<td>{cell['nomda']}</td><td>{cell['sonda']}</td>"
        for cell in report["totals"]["cells"]
    )
    total_row = (
        "<tr class='total'>"
        "<td colspan='2'>Jami</td>"
        f"{totals_cells}"
        f"<td>{report['totals']['jami_nomda']}</td>"
        f"<td>{report['totals']['jami_sonda']}</td>"
        "</tr>"
    )

    return (
        "<table>"
        "<thead>"
        "<tr>"
        "<th rowspan='2'>#</th>"
        "<th rowspan='2'>Kitob turi</th>"
        f"{group_header}"
        "<th colspan='2'>Jami</th>"
        "</tr>"
        f"<tr>{sub_header}<th>NOMDA</th><th>SONDA</th></tr>"
        "</thead>"
        f"<tbody>{''.join(body_rows)}{total_row}</tbody>"
        "</table>"
        "<div class='sign'>Axborot-kutubxona resurslarini butlash, kataloglashtirish va tizimlashtirish bo'limi mudiri: ___________</div>"
    )


def _online_report_word_html(report: dict) -> str:
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label in LANGUAGE_GROUPS)
    body_rows: list[str] = []
    for row in report["rows"]:
        cells = "".join(f"<td>{cell['count']}</td>" for cell in row["cells"])
        body_rows.append(
            f"<tr>"
            f"<td>{row['index']}</td>"
            f"<td class='left'>{html.escape(row['type_name'])}</td>"
            f"{cells}"
            f"<td>{row['jami']}</td>"
            f"</tr>"
        )

    if not body_rows:
        colspan = 3 + len(LANGUAGE_GROUPS)
        body_rows.append(f"<tr><td colspan='{colspan}'>Ma'lumot topilmadi.</td></tr>")

    totals_cells = "".join(f"<td>{cell['count']}</td>" for cell in report["totals"]["cells"])
    total_row = (
        "<tr class='total'>"
        "<td colspan='2'>Jami</td>"
        f"{totals_cells}"
        f"<td>{report['totals']['jami']}</td>"
        "</tr>"
    )
    return (
        "<table>"
        "<thead>"
        "<tr>"
        "<th>#</th>"
        "<th>Kitob turi</th>"
        f"{header}"
        "<th>Jami</th>"
        "</tr>"
        "</thead>"
        f"<tbody>{''.join(body_rows)}{total_row}</tbody>"
        "</table>"
        "<div class='sign'>Axborot-kutubxona resurslarini butlash, kataloglashtirish va tizimlashtirish bo'limi mudiri: ___________</div>"
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    tab: str = "printed",
    db: Session = Depends(get_db),
):
    _guard(request)
    selected_tab = "online" if tab == "online" else "printed"
    language_groups = [{"key": key, "label": label} for key, label in LANGUAGE_GROUPS]

    return templates.TemplateResponse(
        "reports/index.html",
        _ctx(
            request,
            title="Hisobotlar",
            active_menu="reports",
            selected_tab=selected_tab,
            language_groups=language_groups,
            printed_stats=_build_printed_report(db),
            online_stats=_build_online_report(db),
            generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ),
    )


@router.get("/export/printed-word")
@router.get("/export/printed-word/")
async def export_printed_word(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    report = _build_printed_report(db)
    return _word_response(
        filename="bosma_kitob_hisoboti.doc",
        title="Kitob Statistikasi",
        body_html=_printed_report_word_html(report),
    )


@router.get("/export/online-word")
@router.get("/export/online-word/")
async def export_online_word(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    report = _build_online_report(db)
    return _word_response(
        filename="online_kitob_hisoboti.doc",
        title="Elektron Kitoblar Statistikasi",
        body_html=_online_report_word_html(report),
    )
