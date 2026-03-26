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
    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        """
        Kengaytirilgan TemplateResponse. Barcha HTML fayllarga `_("so'z")` chaqiruvini 
        va joriy tilni (`current_lang`) uzatadi.
        """
        request: Request = context.get("request")
        lang = "uz"
        if request:
            lang = request.cookies.get("lang", "uz")
        
        def _(key, **kw):
            return translate(lang, key, **kw)

        system_settings = get_system_settings()
        context["_"] = _
        context["current_lang"] = lang
        context["system_settings"] = system_settings
        context["system_name"] = system_settings.get("system_name", "Tizim")
        context["system_logo_large"] = system_settings.get("logo_large", "/static/img/logo/NARM_large.png")
        context["system_logo_small"] = system_settings.get("logo_small", "/static/img/logo/NARM_small.png")
        return super().TemplateResponse(name, context, *args, **kwargs)
