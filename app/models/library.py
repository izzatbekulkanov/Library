"""
app/models/library.py — Kutubxona va Kitob tizimi modellari (SQLAlchemy)
Django modellaridan konvertatsiya qilingan.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime,
    ForeignKey, Table, Text, BigInteger, Numeric, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


# ══════════════════════════════════════════════════════════════════════
#  Ko'p-ko'pga (M2M) yordamchi jadvallar
# ══════════════════════════════════════════════════════════════════════

library_small_librarians = Table(
    "library_small_librarians", Base.metadata,
    Column("library_id", Integer, ForeignKey("libraries.id"),  primary_key=True),
    Column("user_id",    Integer, ForeignKey("users.id"),      primary_key=True),
    extend_existing=True,
)

book_authors = Table(
    "book_authors", Base.metadata,
    Column("book_id",   Integer, ForeignKey("books.id"),   primary_key=True),
    Column("author_id", Integer, ForeignKey("authors.id"), primary_key=True),
    extend_existing=True,
)

online_book_authors = Table(
    "online_book_authors", Base.metadata,
    Column("online_book_id", Integer, ForeignKey("online_books.id"), primary_key=True),
    Column("author_id",      Integer, ForeignKey("authors.id"),      primary_key=True),
    extend_existing=True,
)


# ══════════════════════════════════════════════════════════════════════
#  LIBRARY
# ══════════════════════════════════════════════════════════════════════

class Library(Base):
    __tablename__ = "libraries"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    name    = Column(String(255), nullable=False,  comment="Kutubxona nomi")
    address = Column(String(255), nullable=False,  comment="Manzili")
    number  = Column(String(255), nullable=False,  comment="Kutubxona raqami")
    email   = Column(String(255), nullable=True,   comment="Kutubxona email")
    phone   = Column(String(20),  nullable=True,   comment="Kutubxona telefon")
    active  = Column(Boolean,     default=False,   comment="Faol yoki emas")

    created_date = Column(Date,     default=datetime.utcnow)
    updated_date = Column(Date,     default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user_id          = Column(Integer, ForeignKey("users.id"), nullable=True, comment="Yaratgan")
    big_librarian_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    small_librarians = relationship("User", secondary=library_small_librarians,
                                    backref="small_librarian_libraries")

    def __repr__(self): return f"<Library {self.name!r}>"


# ══════════════════════════════════════════════════════════════════════
#  AUTHOR
# ══════════════════════════════════════════════════════════════════════

class Author(Base):
    __tablename__ = "authors"
    __table_args__ = {"extend_existing": True}

    id           = Column(Integer,     primary_key=True, index=True)
    name         = Column(String(255), nullable=False, comment="Muallif ismi")
    phone_number = Column(String(300), nullable=True)
    image        = Column(String(500), nullable=True,  comment="Rasm yo'li")
    email        = Column(String(300), nullable=True)
    author_code  = Column(String(50),  nullable=True)
    is_active    = Column(Boolean,     default=True)
    created_at   = Column(DateTime,    default=datetime.utcnow)
    updated_at   = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    added_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self): return f"<Author {self.name!r}>"


# ══════════════════════════════════════════════════════════════════════
#  BOOK TYPE
# ══════════════════════════════════════════════════════════════════════

class BookType(Base):
    __tablename__ = "book_types"
    __table_args__ = {"extend_existing": True}

    id        = Column(Integer,     primary_key=True, index=True)
    name      = Column(String(100), nullable=False, unique=True)
    image     = Column(String(500), nullable=True)
    is_active = Column(Boolean,     default=True)
    created_at = Column(DateTime,   default=datetime.utcnow)
    updated_at = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)

    user_id   = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self): return f"<BookType {self.name!r}>"


# ══════════════════════════════════════════════════════════════════════
#  BBK
# ══════════════════════════════════════════════════════════════════════

class BBK(Base):
    __tablename__ = "bbks"
    __table_args__ = {"extend_existing": True}

    id        = Column(Integer,     primary_key=True, index=True)
    name      = Column(String(100), nullable=False)
    code      = Column(String(255), nullable=False)
    is_active = Column(Boolean,     default=True)
    created_at = Column(DateTime,   default=datetime.utcnow)
    updated_at = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)

    user_id   = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self): return f"<BBK {self.code!r}>"


# ══════════════════════════════════════════════════════════════════════
#  PUBLISHER / PUBLISHED CITY / PUBLICATION YEAR
# ══════════════════════════════════════════════════════════════════════

class Publisher(Base):
    __tablename__ = "publishers"
    __table_args__ = {"extend_existing": True}

    id         = Column(Integer,     primary_key=True, index=True)
    name       = Column(String(255), nullable=False, unique=True, comment="Nashriyot nomi")
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)
    updated_at = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self): return f"<Publisher {self.name!r}>"


class PublishedCity(Base):
    __tablename__ = "published_cities"
    __table_args__ = {"extend_existing": True}

    id         = Column(Integer,     primary_key=True, index=True)
    name       = Column(String(255), nullable=False, unique=True, comment="Nash qilingan shahar nomi")
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)
    updated_at = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self): return f"<PublishedCity {self.name!r}>"


class PublicationYear(Base):
    __tablename__ = "publication_years"
    __table_args__ = {"extend_existing": True}

    id         = Column(Integer, primary_key=True, index=True)
    year       = Column(Integer, nullable=False, unique=True, comment="Nash qilingan yil")
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self): return f"<PublicationYear {self.year}>"


# ══════════════════════════════════════════════════════════════════════
#  BOOK  (jismoniy kitob)
# ══════════════════════════════════════════════════════════════════════

LANGUAGE_CHOICES = [
    'en', 'tr', 'fr', 'uz', 'oz', 'ru', 'de', 'zh', 'es', 'ko', 'kk', 'ky', 'tg', 'qr'
]

class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        Index("ix_books_title",    "title"),
        Index("ix_books_language", "language"),
        {"extend_existing": True},
    )

    id          = Column(Integer,     primary_key=True, index=True)
    title       = Column(String(255), nullable=False, comment="Kitob sarlavhasi")
    external_id = Column(String(100), nullable=True, index=True, comment="Tashqi server kitob IDsi")
    quantity = Column(Integer,     default=0,       comment="Kitoblar soni")
    adad     = Column(BigInteger,  default=0,       comment="Kitobning adadi")
    image    = Column(String(500), nullable=True,   comment="Kitob rasmi yo'li")
    isbn     = Column(String(50),  nullable=True)
    file     = Column(String(500), nullable=True,   comment="Kitob fayli yo'li")
    language = Column(String(10),  nullable=False,  default='uz')
    annotation        = Column(Text,    nullable=True)
    pages             = Column(Integer, nullable=True)
    price             = Column(Numeric(12, 2), default=0)
    total_inventory   = Column(String(255), default='')
    total_copies      = Column(Integer, default=0)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # FK
    added_by_id        = Column(Integer, ForeignKey("users.id"),            nullable=True)
    book_type_id       = Column(Integer, ForeignKey("book_types.id"),       nullable=True)
    bbk_id             = Column(Integer, ForeignKey("bbks.id"),             nullable=True)
    publication_year_id= Column(Integer, ForeignKey("publication_years.id"),nullable=True)
    publisher_id       = Column(Integer, ForeignKey("publishers.id"),       nullable=True)
    published_city_id  = Column(Integer, ForeignKey("published_cities.id"), nullable=True)

    # Relationships (templates/UI uses these)
    added_by         = relationship("User",            foreign_keys=[added_by_id])
    book_type        = relationship("BookType",        foreign_keys=[book_type_id])
    bbk              = relationship("BBK",             foreign_keys=[bbk_id])
    publication_year = relationship("PublicationYear", foreign_keys=[publication_year_id])
    publisher        = relationship("Publisher",       foreign_keys=[publisher_id])
    published_city   = relationship("PublishedCity",   foreign_keys=[published_city_id])

    # M2M
    authors = relationship("Author", secondary=book_authors, backref="books")
    
    # 1-to-many relationships
    copies = relationship("BookCopy", back_populates="book", cascade="all, delete-orphan")

    def __repr__(self): return f"<Book {self.title!r}>"


# ══════════════════════════════════════════════════════════════════════
#  BOOK COPY  (kitob nusxasi)
# ══════════════════════════════════════════════════════════════════════

class BookCopy(Base):
    __tablename__ = "book_copies"
    __table_args__ = {"extend_existing": True}

    id               = Column(Integer,    primary_key=True, index=True)
    book_id_code     = Column(String(9),  nullable=True,  unique=True, comment="Kitob identifikatori")
    inventory_number = Column(String(50), nullable=True)
    is_print         = Column(Boolean,    default=False)
    id_card_printed  = Column(Boolean,    default=False, comment="ID karta chop etilganmi")
    id_card_printed_at = Column(DateTime, nullable=True)
    qr_printed       = Column(Boolean,    default=False, comment="QR kod chop etilganmi")
    qr_printed_at    = Column(DateTime,   nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)
    updated_at       = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)

    status     = Column(String(20), default='not_sended',
                        comment="accepted | sent | not_accepted | not_sended")
    have_status= Column(String(20), default='yes',
                        comment="yes | busy | no")

    original_book_id = Column(Integer, ForeignKey("books.id"),     nullable=True)
    library_id       = Column(Integer, ForeignKey("libraries.id"), nullable=True)
    
    # relationship
    book = relationship("Book", back_populates="copies")
    library = relationship("Library", foreign_keys=[library_id])

    def __repr__(self): return f"<BookCopy id={self.id}>"


# ══════════════════════════════════════════════════════════════════════
#  ONLINE BOOK  (elektron kitob)
# ══════════════════════════════════════════════════════════════════════

class OnlineBook(Base):
    __tablename__ = "online_books"
    __table_args__ = {"extend_existing": True}

    id          = Column(Integer,     primary_key=True, index=True)
    title       = Column(String(255), nullable=False, comment="Kitob sarlavhasi")
    external_id = Column(String(100), nullable=True, index=True, comment="Tashqi server kitob IDsi")
    language    = Column(String(10),  default='uz')
    isbn        = Column(String(50),  nullable=True)
    annotation  = Column(Text,        nullable=True)
    created_at  = Column(DateTime,    default=datetime.utcnow)
    updated_at  = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    # FK
    library_id   = Column(Integer, ForeignKey("libraries.id"), nullable=True)
    added_by_id  = Column(Integer, ForeignKey("users.id"),     nullable=True)
    bbk_id       = Column(Integer, ForeignKey("bbks.id"),      nullable=True)
    book_type_id = Column(Integer, ForeignKey("book_types.id"),nullable=True)

    # M2M
    authors = relationship("Author", secondary=online_book_authors, backref="online_books")
    # 1-ko'p (editions)
    editions = relationship("BookEdition", back_populates="book", cascade="all, delete-orphan")

    def __repr__(self): return f"<OnlineBook {self.title!r}>"


# ══════════════════════════════════════════════════════════════════════
#  BOOK EDITION  (kitob versiyasi)
# ══════════════════════════════════════════════════════════════════════

class BookEdition(Base):
    __tablename__ = "book_editions"
    __table_args__ = (
        Index("ix_editions_book", "book_id"),
        {"extend_existing": True},
    )

    id         = Column(Integer, primary_key=True, index=True)
    pages      = Column(Integer, nullable=True)
    adad       = Column(BigInteger, default=0)
    status     = Column(String(20), default='undistributed',
                        comment="distributed | undistributed")
    image      = Column(String(500), nullable=True)
    file       = Column(String(500), nullable=True)
    audio_file = Column(String(500), nullable=True)
    created_at = Column(DateTime,    default=datetime.utcnow)
    updated_at = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    # FK
    book_id            = Column(Integer, ForeignKey("online_books.id"),    nullable=False)
    publication_year_id= Column(Integer, ForeignKey("publication_years.id"), nullable=True)
    publisher_id       = Column(Integer, ForeignKey("publishers.id"),      nullable=True)
    published_city_id  = Column(Integer, ForeignKey("published_cities.id"),nullable=True)

    # Relationships
    book = relationship("OnlineBook", back_populates="editions")

    def __repr__(self):
        return f"<BookEdition id={self.id} book_id={self.book_id}>"
