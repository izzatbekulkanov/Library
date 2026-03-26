from __future__ import annotations

import json
import os
import time
from typing import Any

SYSTEM_SETTINGS_PATH = os.getenv(
    "APP_SYSTEM_SETTINGS_PATH",
    os.path.join("app", "core", "system_settings.json"),
)

_CACHE: dict[str, Any] | None = None
_CACHE_MTIME: float = -1.0


def _default_settings() -> dict[str, Any]:
    return {
        "system_name": "Kutubxona boshqaruvi",
        "logo_large": "/static/img/logo/NARM_large.png",
        "logo_small": "/static/img/logo/NARM_small.png",
        "maintenance_mode": False,
        "maintenance_message": "Tizimda texnik ishlar olib borilmoqda.",
        "block_book_delete": False,
    }


def _normalize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_settings()
    if not isinstance(raw, dict):
        return base

    name = str(raw.get("system_name") or "").strip()
    if name:
        base["system_name"] = name

    logo_large = str(raw.get("logo_large") or "").strip()
    logo_small = str(raw.get("logo_small") or "").strip()
    if logo_large:
        base["logo_large"] = logo_large
    if logo_small:
        base["logo_small"] = logo_small

    base["maintenance_mode"] = bool(raw.get("maintenance_mode", False))
    base["block_book_delete"] = bool(raw.get("block_book_delete", False))

    maintenance_message = str(raw.get("maintenance_message") or "").strip()
    if maintenance_message:
        base["maintenance_message"] = maintenance_message
    return base


def _read_settings_file() -> dict[str, Any]:
    try:
        if os.path.isfile(SYSTEM_SETTINGS_PATH):
            with open(SYSTEM_SETTINGS_PATH, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
                if isinstance(parsed, dict):
                    return parsed
    except Exception:
        pass
    return {}


def _write_settings_file(data: dict[str, Any]) -> None:
    settings_dir = os.path.dirname(SYSTEM_SETTINGS_PATH)
    if settings_dir:
        os.makedirs(settings_dir, exist_ok=True)
    with open(SYSTEM_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def get_system_settings(force_reload: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME
    mtime = -1.0
    try:
        if os.path.isfile(SYSTEM_SETTINGS_PATH):
            mtime = os.path.getmtime(SYSTEM_SETTINGS_PATH)
    except Exception:
        mtime = -1.0

    if force_reload or _CACHE is None or mtime != _CACHE_MTIME:
        loaded = _normalize_settings(_read_settings_file())
        _CACHE = loaded
        _CACHE_MTIME = mtime if mtime >= 0 else time.time()

    return dict(_CACHE or _default_settings())


def save_system_settings(partial: dict[str, Any]) -> dict[str, Any]:
    current = get_system_settings(force_reload=True)
    merged = dict(current)
    merged.update(partial or {})
    normalized = _normalize_settings(merged)
    _write_settings_file(normalized)
    return get_system_settings(force_reload=True)


def is_maintenance_mode() -> bool:
    return bool(get_system_settings().get("maintenance_mode", False))


def is_book_delete_blocked() -> bool:
    return bool(get_system_settings().get("block_book_delete", False))
