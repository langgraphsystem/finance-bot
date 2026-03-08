"""i18n strings and localized button builder for video action skill."""

from src.skills._i18n import register_strings

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Button labels
        "btn_content_plan": "📋 Content plan",
        "btn_post": "📝 Post",
        "btn_steps": "📌 Steps",
        "btn_save": "💾 Save",
        "btn_remind": "⏰ Remind me",
        "btn_similar": "🔍 Similar",
        "btn_deeper": "📖 Deeper",
        "btn_translate": "🌐 Translate",
        "btn_article": "📄 Article",
        "btn_quotes": "💬 Key quotes",
        "btn_script": "📝 Script",
        "btn_save_content": "💾 Save this",
        # Response strings
        "no_video": "No recent video found. Send a YouTube or TikTok link first.",
        "err_analysis": "Could not generate analysis.",
        "err_steps": "No steps found.",
        "err_quotes": "No quotes extracted.",
        "err_content_plan": "Could not generate content plan.",
        "err_post": "Could not generate post.",
        "err_article": "Could not generate article.",
        "err_script": "Could not generate script.",
        "err_summary": "Could not summarize.",
        "err_translate": "Could not translate.",
        "saved_title": "Video saved to memory:",
        "saved_content_title": "Saved to memory.",
        "saved_note": "You can ask me about it later.",
        "remind_prompt": "When do you want to be reminded to watch this video?",
        "remind_hint": (
            'Reply with time, e.g. <b>"remind me in 2 hours"</b> '
            'or <b>"tomorrow at 9am"</b>'
        ),
        "similar_title": "Similar videos for:",
    },
    "ru": {
        "btn_content_plan": "📋 Контент-план",
        "btn_post": "📝 Пост",
        "btn_steps": "📌 Шаги",
        "btn_save": "💾 Сохранить",
        "btn_remind": "⏰ Напомнить",
        "btn_similar": "🔍 Похожие",
        "btn_deeper": "📖 Подробнее",
        "btn_translate": "🌐 Перевести",
        "btn_article": "📄 Статья",
        "btn_quotes": "💬 Ключевые цитаты",
        "btn_script": "📝 Сценарий",
        "btn_save_content": "💾 Сохранить это",
        "no_video": "Видео не найдено. Сначала отправьте ссылку на YouTube или TikTok.",
        "err_analysis": "Не удалось сгенерировать анализ.",
        "err_steps": "Шаги не найдены.",
        "err_quotes": "Цитаты не найдены.",
        "err_content_plan": "Не удалось составить контент-план.",
        "err_post": "Не удалось создать пост.",
        "err_article": "Не удалось написать статью.",
        "err_script": "Не удалось написать сценарий.",
        "err_summary": "Не удалось сделать резюме.",
        "err_translate": "Не удалось перевести.",
        "saved_title": "Видео сохранено в память:",
        "saved_content_title": "Сохранено в память.",
        "saved_note": "Можете спросить меня об этом позже.",
        "remind_prompt": "Когда напомнить посмотреть это видео?",
        "remind_hint": (
            "Ответьте временем, например <b>«напомни через 2 часа»</b> "
            "или <b>«завтра в 9 утра»</b>"
        ),
        "similar_title": "Похожие видео по теме:",
    },
    "es": {
        "btn_content_plan": "📋 Plan de contenido",
        "btn_post": "📝 Publicación",
        "btn_steps": "📌 Pasos",
        "btn_save": "💾 Guardar",
        "btn_remind": "⏰ Recordarme",
        "btn_similar": "🔍 Similares",
        "btn_deeper": "📖 Más detalles",
        "btn_translate": "🌐 Traducir",
        "btn_article": "📄 Artículo",
        "btn_quotes": "💬 Citas clave",
        "btn_script": "📝 Guión",
        "btn_save_content": "💾 Guardar esto",
        "no_video": "No se encontró video reciente. Envía un enlace de YouTube o TikTok primero.",
        "err_analysis": "No se pudo generar el análisis.",
        "err_steps": "No se encontraron pasos.",
        "err_quotes": "No se encontraron citas.",
        "err_content_plan": "No se pudo generar el plan de contenido.",
        "err_post": "No se pudo generar la publicación.",
        "err_article": "No se pudo generar el artículo.",
        "err_script": "No se pudo generar el guión.",
        "err_summary": "No se pudo resumir.",
        "err_translate": "No se pudo traducir.",
        "saved_title": "Video guardado en memoria:",
        "saved_content_title": "Guardado en memoria.",
        "saved_note": "Puedes preguntarme sobre él más tarde.",
        "remind_prompt": "¿Cuándo quieres que te recuerde ver este video?",
        "remind_hint": (
            "Responde con la hora, p.ej. <b>«recuérdame en 2 horas»</b> "
            "o <b>«mañana a las 9am»</b>"
        ),
        "similar_title": "Videos similares para:",
    },
}

register_strings("video_action", _STRINGS)

# Button definitions — order matters (shown as inline keyboard rows)
# Displayed after initial video analysis (2 per row via builder.adjust(2))
_BUTTON_KEYS = [
    ("btn_deeper", "video:deeper"),
    ("btn_steps", "video:steps"),
    ("btn_content_plan", "video:content_plan"),
    ("btn_post", "video:post"),
    ("btn_article", "video:article"),
    ("btn_quotes", "video:quotes"),
    ("btn_translate", "video:translate"),
    ("btn_similar", "video:similar"),
    ("btn_remind", "video:remind"),
    ("btn_save", "video:save"),
]

_WRITING_BUTTON_KEYS = [
    ("btn_content_plan", "video:content_plan"),
    ("btn_article", "video:article"),
    ("btn_script", "video:script"),
    ("btn_save", "video:save"),
]


def _lang(language: str) -> str:
    """Normalize language to one of the three static keys."""
    lang = (language or "en")[:2].lower()
    return lang if lang in _STRINGS else "en"


def t(key: str, language: str) -> str:
    """Translate a video_action string."""
    return _STRINGS[_lang(language)].get(key, _STRINGS["en"].get(key, key))


def get_video_buttons(language: str) -> list[dict]:
    """Return localized video action buttons."""
    lang = _lang(language)
    strings = _STRINGS[lang]
    return [{"text": strings[k], "callback": cb} for k, cb in _BUTTON_KEYS]


def get_writing_buttons(language: str) -> list[dict]:
    """Return localized writing follow-up buttons (used after post generation)."""
    lang = _lang(language)
    strings = _STRINGS[lang]
    return [{"text": strings[k], "callback": cb} for k, cb in _WRITING_BUTTON_KEYS]
