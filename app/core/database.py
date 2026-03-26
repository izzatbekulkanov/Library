from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_CONFIG_PATH = os.getenv("APP_DB_CONFIG_PATH", os.path.join("app", "core", "db_config.json"))


def _default_database_config() -> dict[str, Any]:
    return {
        "db_type": "sqlite",
        "sqlite": {
            "path": "./sql_app.db",
        },
        "postgresql": {
            "host": "localhost",
            "port": 5432,
            "database": "library",
            "username": "postgres",
            "password": "",
        },
    }


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_db_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"postgres", "postgresql", "pgsql"}:
        return "postgresql"
    return "sqlite"


def _normalize_database_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = _default_database_config()
    if not isinstance(raw, dict):
        return cfg

    cfg["db_type"] = _normalize_db_type(raw.get("db_type") or raw.get("driver"))

    sqlite_raw = raw.get("sqlite")
    if isinstance(sqlite_raw, dict):
        sqlite_path = str(sqlite_raw.get("path") or "").strip()
        if sqlite_path:
            cfg["sqlite"]["path"] = sqlite_path
    sqlite_flat = str(raw.get("sqlite_path") or raw.get("sqlitePath") or "").strip()
    if sqlite_flat:
        cfg["sqlite"]["path"] = sqlite_flat

    pg_raw = raw.get("postgresql")
    if isinstance(pg_raw, dict):
        host = str(pg_raw.get("host") or "").strip()
        database = str(pg_raw.get("database") or "").strip()
        username = str(pg_raw.get("username") or "").strip()
        password = str(pg_raw.get("password") or "").strip()
        port = _to_int(pg_raw.get("port"), 5432)

        if host:
            cfg["postgresql"]["host"] = host
        if database:
            cfg["postgresql"]["database"] = database
        if username:
            cfg["postgresql"]["username"] = username
        if password:
            cfg["postgresql"]["password"] = password
        cfg["postgresql"]["port"] = max(1, min(port, 65535))

    pg_host = str(raw.get("pg_host") or raw.get("pgHost") or "").strip()
    pg_database = str(raw.get("pg_database") or raw.get("pgDatabase") or "").strip()
    pg_username = str(raw.get("pg_username") or raw.get("pgUsername") or "").strip()
    pg_password = str(raw.get("pg_password") or raw.get("pgPassword") or "").strip()
    pg_port = _to_int(raw.get("pg_port") or raw.get("pgPort"), 5432)

    if pg_host:
        cfg["postgresql"]["host"] = pg_host
    if pg_database:
        cfg["postgresql"]["database"] = pg_database
    if pg_username:
        cfg["postgresql"]["username"] = pg_username
    if pg_password:
        cfg["postgresql"]["password"] = pg_password
    if pg_port:
        cfg["postgresql"]["port"] = max(1, min(pg_port, 65535))

    return cfg


def _build_database_url(cfg: dict[str, Any]) -> str:
    db_type = _normalize_db_type(cfg.get("db_type"))
    if db_type == "postgresql":
        pg = cfg.get("postgresql", {}) if isinstance(cfg.get("postgresql"), dict) else {}
        host = str(pg.get("host") or "localhost").strip()
        port = _to_int(pg.get("port"), 5432)
        database = str(pg.get("database") or "").strip()
        username = str(pg.get("username") or "").strip()
        password = str(pg.get("password") or "").strip()
        return (
            f"postgresql://{quote_plus(username)}:{quote_plus(password)}@"
            f"{host}:{port}/{database}"
        )

    sqlite_cfg = cfg.get("sqlite", {}) if isinstance(cfg.get("sqlite"), dict) else {}
    sqlite_path = str(sqlite_cfg.get("path") or "./sql_app.db").strip()
    if sqlite_path.startswith("sqlite:///"):
        return sqlite_path
    if sqlite_path == ":memory:":
        return "sqlite:///:memory:"
    return f"sqlite:///{sqlite_path.replace('\\', '/')}"


def _set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()
    except Exception:
        pass


def _create_engine_from_config(cfg: dict[str, Any]) -> Engine:
    db_type = _normalize_db_type(cfg.get("db_type"))
    url = _build_database_url(cfg)
    if db_type == "postgresql":
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
        )

    sqlite_engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 60},
    )
    event.listen(sqlite_engine, "connect", _set_sqlite_pragma)
    return sqlite_engine


def _read_database_config_file() -> dict[str, Any]:
    try:
        if os.path.isfile(DB_CONFIG_PATH):
            with open(DB_CONFIG_PATH, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
                if isinstance(parsed, dict):
                    return parsed
    except Exception:
        pass
    return {}


def _write_database_config_file(cfg: dict[str, Any]) -> None:
    cfg_dir = os.path.dirname(DB_CONFIG_PATH)
    if cfg_dir:
        os.makedirs(cfg_dir, exist_ok=True)
    with open(DB_CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def get_database_config(mask_password: bool = True) -> dict[str, Any]:
    pg = ACTIVE_DB_CONFIG.get("postgresql", {}) if isinstance(ACTIVE_DB_CONFIG.get("postgresql"), dict) else {}
    password = str(pg.get("password") or "")
    return {
        "db_type": _normalize_db_type(ACTIVE_DB_CONFIG.get("db_type")),
        "sqlite_path": str((ACTIVE_DB_CONFIG.get("sqlite") or {}).get("path") or "./sql_app.db"),
        "postgresql": {
            "host": str(pg.get("host") or "localhost"),
            "port": _to_int(pg.get("port"), 5432),
            "database": str(pg.get("database") or ""),
            "username": str(pg.get("username") or ""),
            "password": "" if mask_password else password,
            "has_password": bool(password),
        },
    }


def build_database_config_from_payload(
    payload: dict[str, Any] | None,
    current_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _normalize_database_config(current_config or ACTIVE_DB_CONFIG)
    data = payload if isinstance(payload, dict) else {}

    next_db_type = _normalize_db_type(data.get("db_type") or data.get("dbType") or base.get("db_type"))
    base["db_type"] = next_db_type

    sqlite_path = str(data.get("sqlite_path") or data.get("sqlitePath") or "").strip()
    if sqlite_path:
        base["sqlite"]["path"] = sqlite_path

    pg_payload = data.get("postgresql") if isinstance(data.get("postgresql"), dict) else {}
    pg = base["postgresql"]

    host = str(data.get("pg_host") or data.get("pgHost") or pg_payload.get("host") or "").strip()
    database = str(data.get("pg_database") or data.get("pgDatabase") or pg_payload.get("database") or "").strip()
    username = str(data.get("pg_username") or data.get("pgUsername") or pg_payload.get("username") or "").strip()

    if host:
        pg["host"] = host
    if database:
        pg["database"] = database
    if username:
        pg["username"] = username

    pg_port_raw = data.get("pg_port")
    if pg_port_raw is None:
        pg_port_raw = data.get("pgPort")
    if pg_port_raw is None:
        pg_port_raw = pg_payload.get("port")
    if pg_port_raw not in (None, ""):
        pg["port"] = max(1, min(_to_int(pg_port_raw, 5432), 65535))

    password_from_flat = data.get("pg_password")
    if password_from_flat is None:
        password_from_flat = data.get("pgPassword")
    if password_from_flat is None:
        password_from_flat = pg_payload.get("password")
    if password_from_flat is not None:
        new_password = str(password_from_flat).strip()
        if new_password:
            pg["password"] = new_password

    if next_db_type == "sqlite":
        sqlite_final = str(base["sqlite"].get("path") or "").strip()
        if not sqlite_final:
            raise ValueError("SQLite fayl yo'lini kiriting.")
        return _normalize_database_config(base)

    missing: list[str] = []
    if not str(pg.get("host") or "").strip():
        missing.append("host")
    if _to_int(pg.get("port"), 0) <= 0:
        missing.append("port")
    if not str(pg.get("database") or "").strip():
        missing.append("database")
    if not str(pg.get("username") or "").strip():
        missing.append("username")
    if not str(pg.get("password") or "").strip():
        missing.append("password")
    if missing:
        raise ValueError(
            "PostgreSQL uchun quyidagi maydonlar majburiy: " + ", ".join(missing)
        )
    return _normalize_database_config(base)


def test_database_config(cfg: dict[str, Any]) -> None:
    test_engine = _create_engine_from_config(_normalize_database_config(cfg))
    try:
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        test_engine.dispose()


def apply_database_config(cfg: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    global ACTIVE_DB_CONFIG, SQLALCHEMY_DATABASE_URL, engine
    normalized = _normalize_database_config(cfg)
    test_database_config(normalized)

    new_url = _build_database_url(normalized)
    new_engine = _create_engine_from_config(normalized)
    with new_engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    old_engine = engine
    SessionLocal.configure(bind=new_engine)
    engine = new_engine
    SQLALCHEMY_DATABASE_URL = new_url
    ACTIVE_DB_CONFIG = normalized

    if persist:
        _write_database_config_file(normalized)

    try:
        old_engine.dispose()
    except Exception:
        pass

    return get_database_config(mask_password=True)


ACTIVE_DB_CONFIG = _normalize_database_config(_read_database_config_file())
SQLALCHEMY_DATABASE_URL = _build_database_url(ACTIVE_DB_CONFIG)
engine = _create_engine_from_config(ACTIVE_DB_CONFIG)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_book_copy_print_columns() -> None:
    """Legacy DB uchun book_copies jadvaliga yangi print status ustunlarini qo'shish.
    Jadval yoki ustun allaqachon mavjud bo'lsa, xatolar e'tiborsiz qoldiriladi."""
    statements = [
        "ALTER TABLE book_copies ADD COLUMN id_card_printed BOOLEAN DEFAULT 0",
        "ALTER TABLE book_copies ADD COLUMN id_card_printed_at DATETIME",
        "ALTER TABLE book_copies ADD COLUMN qr_printed BOOLEAN DEFAULT 0",
        "ALTER TABLE book_copies ADD COLUMN qr_printed_at DATETIME",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception:
                # duplicate column yoki jadval yo'qligi holatlari
                pass


def ensure_user_menu_permissions_column() -> None:
    """Legacy DB uchun users jadvaliga menu_permissions ustunini qo'shish."""
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN menu_permissions VARCHAR(1024)"))
        except Exception:
            # duplicate column yoki jadval yo'qligi holatlari
            pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
