from fastapi.templating import Jinja2Templates
from fastapi import Request
import json
import os
from app.core.system_settings import get_system_settings

locales_dir = os.path.join(os.path.dirname(__file__), "..", "locales")

def load_json(lang):
    path = os.path.join(locales_dir, f"{lang}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

translations = {
    "uz": load_json("uz"),
    "ru": load_json("ru"),
    "en": load_json("en")
}

def translate(lang: str, key: str, **kwargs) -> str:
    lang_dict = translations.get(lang, translations["uz"])
    
    text = lang_dict.get(key)
    if text is None:
        # Fallback to uzbek, or return the raw key itself if not translated
        text = translations["uz"].get(key, key)
    
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text

class I18nJinja2Templates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
        """
        Kengaytirilgan TemplateResponse.
        Starlette'ning eski va yangi chaqiruv usullarini qabul qiladi, lekin
        ichkarida yangi `request-first` usulga o'tkazadi.
        """
        if args:
            if isinstance(args[0], str):
                # Old style: TemplateResponse("page.html", {"request": request}, ...)
                name = args[0]
                context = args[1] if len(args) > 1 else kwargs.get("context", {})
                status_code = args[2] if len(args) > 2 else kwargs.get("status_code", 200)
                headers = args[3] if len(args) > 3 else kwargs.get("headers")
                media_type = args[4] if len(args) > 4 else kwargs.get("media_type")
                background = args[5] if len(args) > 5 else kwargs.get("background")
                request: Request | None = context.get("request") if isinstance(context, dict) else None
            else:
                # New style: TemplateResponse(request, "page.html", ...)
                request = args[0]
                name = args[1] if len(args) > 1 else kwargs["name"]
                context = args[2] if len(args) > 2 else kwargs.get("context", {})
                status_code = args[3] if len(args) > 3 else kwargs.get("status_code", 200)
                headers = args[4] if len(args) > 4 else kwargs.get("headers")
                media_type = args[5] if len(args) > 5 else kwargs.get("media_type")
                background = args[6] if len(args) > 6 else kwargs.get("background")
        else:
            context = kwargs.get("context", {})
            request = kwargs.get("request", context.get("request") if isinstance(context, dict) else None)
            name = kwargs["name"]
            status_code = kwargs.get("status_code", 200)
            headers = kwargs.get("headers")
            media_type = kwargs.get("media_type")
            background = kwargs.get("background")

        if request is None:
            raise ValueError('context must include a "request" key')

        lang = "uz"
        try:
            lang = request.cookies.get("lang", "uz")
        except Exception:
            lang = "uz"

        def _(key, **kw):
            return translate(lang, key, **kw)

        system_settings = get_system_settings()
        context = dict(context or {})
        context["_"] = _
        context["current_lang"] = lang
        context["system_settings"] = system_settings
        context["system_name"] = system_settings.get("system_name", "Tizim")
        context["system_logo_large"] = system_settings.get("logo_large", "/static/img/logo/NARM_large.png")
        context["system_logo_small"] = system_settings.get("logo_small", "/static/img/logo/NARM_small.png")
        context.setdefault("request", request)
        return super().TemplateResponse(
            request,
            name,
            context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )
