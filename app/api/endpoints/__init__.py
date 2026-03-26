from fastapi import APIRouter

router = APIRouter()

from . import users, libraries, book_types, authors, publishers, books, online_books, reports, external_books, sozlamalar
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(libraries.router, prefix="/libraries", tags=["libraries"])
router.include_router(book_types.router, prefix="/book_types", tags=["book_types"])
router.include_router(authors.router, prefix="/authors", tags=["authors"])
router.include_router(publishers.router, prefix="/publishers", tags=["publishers"])
router.include_router(books.router, prefix="/books", tags=["books"])
router.include_router(online_books.router, prefix="/online-books", tags=["online_books"])
router.include_router(reports.router, prefix="/reports", tags=["reports"])
router.include_router(external_books.router, prefix="/external-books", tags=["external_books"])
router.include_router(sozlamalar.router, prefix="/sozlamalar", tags=["sozlamalar"])
