"""i18n strings and localized button builder for video action skill."""

from src.skills._i18n import register_strings

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
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
    "uk": {
        "btn_content_plan": "📋 Контент-план",
        "btn_post": "📝 Пост",
        "btn_steps": "📌 Кроки",
        "btn_save": "💾 Зберегти",
        "btn_remind": "⏰ Нагадати",
        "btn_similar": "🔍 Схожі",
        "btn_deeper": "📖 Детальніше",
        "btn_translate": "🌐 Перекласти",
        "btn_article": "📄 Стаття",
        "btn_quotes": "💬 Ключові цитати",
        "btn_script": "📝 Сценарій",
        "btn_save_content": "💾 Зберегти це",
        "no_video": "Відео не знайдено. Спочатку надішліть посилання на YouTube або TikTok.",
        "err_analysis": "Не вдалося згенерувати аналіз.",
        "err_steps": "Кроки не знайдено.",
        "err_quotes": "Цитати не знайдено.",
        "err_content_plan": "Не вдалося скласти контент-план.",
        "err_post": "Не вдалося створити пост.",
        "err_article": "Не вдалося написати статтю.",
        "err_script": "Не вдалося написати сценарій.",
        "err_summary": "Не вдалося зробити резюме.",
        "err_translate": "Не вдалося перекласти.",
        "saved_title": "Відео збережено в пам'ять:",
        "saved_content_title": "Збережено в пам'ять.",
        "saved_note": "Можете запитати мене про це пізніше.",
        "remind_prompt": "Коли нагадати переглянути це відео?",
        "remind_hint": (
            "Відповідайте часом, наприклад <b>«нагадай через 2 години»</b> "
            "або <b>«завтра о 9 ранку»</b>"
        ),
        "similar_title": "Схожі відео за темою:",
    },
    "fr": {
        "btn_content_plan": "📋 Plan de contenu",
        "btn_post": "📝 Publication",
        "btn_steps": "📌 Étapes",
        "btn_save": "💾 Sauvegarder",
        "btn_remind": "⏰ Me rappeler",
        "btn_similar": "🔍 Similaires",
        "btn_deeper": "📖 Plus de détails",
        "btn_translate": "🌐 Traduire",
        "btn_article": "📄 Article",
        "btn_quotes": "💬 Citations clés",
        "btn_script": "📝 Script",
        "btn_save_content": "💾 Sauvegarder ça",
        "no_video": "Aucune vidéo récente. Envoyez d'abord un lien YouTube ou TikTok.",
        "err_analysis": "Impossible de générer l'analyse.",
        "err_steps": "Aucune étape trouvée.",
        "err_quotes": "Aucune citation extraite.",
        "err_content_plan": "Impossible de générer le plan de contenu.",
        "err_post": "Impossible de générer la publication.",
        "err_article": "Impossible de générer l'article.",
        "err_script": "Impossible de générer le script.",
        "err_summary": "Impossible de résumer.",
        "err_translate": "Impossible de traduire.",
        "saved_title": "Vidéo sauvegardée en mémoire :",
        "saved_content_title": "Sauvegardé en mémoire.",
        "saved_note": "Vous pouvez me demander à ce sujet plus tard.",
        "remind_prompt": "Quand voulez-vous être rappelé de regarder cette vidéo ?",
        "remind_hint": (
            'Répondez avec une heure, p.ex. <b>«rappelle-moi dans 2 heures»</b> '
            'ou <b>«demain à 9h»</b>'
        ),
        "similar_title": "Vidéos similaires pour :",
    },
    "de": {
        "btn_content_plan": "📋 Inhaltsplan",
        "btn_post": "📝 Beitrag",
        "btn_steps": "📌 Schritte",
        "btn_save": "💾 Speichern",
        "btn_remind": "⏰ Erinnern",
        "btn_similar": "🔍 Ähnliche",
        "btn_deeper": "📖 Mehr Details",
        "btn_translate": "🌐 Übersetzen",
        "btn_article": "📄 Artikel",
        "btn_quotes": "💬 Schlüsselzitate",
        "btn_script": "📝 Skript",
        "btn_save_content": "💾 Das speichern",
        "no_video": "Kein aktuelles Video gefunden. Senden Sie zuerst einen YouTube- oder TikTok-Link.",
        "err_analysis": "Analyse konnte nicht generiert werden.",
        "err_steps": "Keine Schritte gefunden.",
        "err_quotes": "Keine Zitate extrahiert.",
        "err_content_plan": "Inhaltsplan konnte nicht generiert werden.",
        "err_post": "Beitrag konnte nicht generiert werden.",
        "err_article": "Artikel konnte nicht generiert werden.",
        "err_script": "Skript konnte nicht generiert werden.",
        "err_summary": "Zusammenfassung fehlgeschlagen.",
        "err_translate": "Übersetzung fehlgeschlagen.",
        "saved_title": "Video im Speicher gespeichert:",
        "saved_content_title": "Im Speicher gespeichert.",
        "saved_note": "Sie können mich später danach fragen.",
        "remind_prompt": "Wann möchten Sie an dieses Video erinnert werden?",
        "remind_hint": (
            'Antworten Sie mit einer Zeit, z.B. <b>«erinnere mich in 2 Stunden»</b> '
            'oder <b>«morgen um 9 Uhr»</b>'
        ),
        "similar_title": "Ähnliche Videos für:",
    },
    "pt": {
        "btn_content_plan": "📋 Plano de conteúdo",
        "btn_post": "📝 Publicação",
        "btn_steps": "📌 Passos",
        "btn_save": "💾 Salvar",
        "btn_remind": "⏰ Lembrar-me",
        "btn_similar": "🔍 Similares",
        "btn_deeper": "📖 Mais detalhes",
        "btn_translate": "🌐 Traduzir",
        "btn_article": "📄 Artigo",
        "btn_quotes": "💬 Citações-chave",
        "btn_script": "📝 Roteiro",
        "btn_save_content": "💾 Salvar isso",
        "no_video": "Nenhum vídeo recente. Envie um link do YouTube ou TikTok primeiro.",
        "err_analysis": "Não foi possível gerar a análise.",
        "err_steps": "Nenhum passo encontrado.",
        "err_quotes": "Nenhuma citação extraída.",
        "err_content_plan": "Não foi possível gerar o plano de conteúdo.",
        "err_post": "Não foi possível gerar a publicação.",
        "err_article": "Não foi possível gerar o artigo.",
        "err_script": "Não foi possível gerar o roteiro.",
        "err_summary": "Não foi possível resumir.",
        "err_translate": "Não foi possível traduzir.",
        "saved_title": "Vídeo salvo na memória:",
        "saved_content_title": "Salvo na memória.",
        "saved_note": "Você pode me perguntar sobre isso mais tarde.",
        "remind_prompt": "Quando você quer ser lembrado de assistir este vídeo?",
        "remind_hint": (
            'Responda com uma hora, p.ex. <b>«me lembre em 2 horas»</b> '
            'ou <b>«amanhã às 9h»</b>'
        ),
        "similar_title": "Vídeos similares para:",
    },
    "ar": {
        "btn_content_plan": "📋 خطة المحتوى",
        "btn_post": "📝 منشور",
        "btn_steps": "📌 الخطوات",
        "btn_save": "💾 حفظ",
        "btn_remind": "⏰ تذكيري",
        "btn_similar": "🔍 مشابه",
        "btn_deeper": "📖 مزيد من التفاصيل",
        "btn_translate": "🌐 ترجمة",
        "btn_article": "📄 مقالة",
        "btn_quotes": "💬 اقتباسات رئيسية",
        "btn_script": "📝 نص",
        "btn_save_content": "💾 حفظ هذا",
        "no_video": "لم يتم العثور على فيديو حديث. أرسل رابط YouTube أو TikTok أولاً.",
        "err_analysis": "تعذر إنشاء التحليل.",
        "err_steps": "لم يتم العثور على خطوات.",
        "err_quotes": "لم يتم استخراج اقتباسات.",
        "err_content_plan": "تعذر إنشاء خطة المحتوى.",
        "err_post": "تعذر إنشاء المنشور.",
        "err_article": "تعذر إنشاء المقالة.",
        "err_script": "تعذر إنشاء النص.",
        "err_summary": "تعذر التلخيص.",
        "err_translate": "تعذرت الترجمة.",
        "saved_title": "تم حفظ الفيديو في الذاكرة:",
        "saved_content_title": "تم الحفظ في الذاكرة.",
        "saved_note": "يمكنك سؤالي عنه لاحقاً.",
        "remind_prompt": "متى تريد أن يتم تذكيرك بمشاهدة هذا الفيديو؟",
        "remind_hint": (
            'أجب بوقت، مثل <b>«ذكرني بعد ساعتين»</b> '
            'أو <b>«غداً الساعة 9»</b>'
        ),
        "similar_title": "فيديوهات مشابهة لـ:",
    },
    "tr": {
        "btn_content_plan": "📋 İçerik planı",
        "btn_post": "📝 Gönderi",
        "btn_steps": "📌 Adımlar",
        "btn_save": "💾 Kaydet",
        "btn_remind": "⏰ Hatırlat",
        "btn_similar": "🔍 Benzer",
        "btn_deeper": "📖 Daha fazla",
        "btn_translate": "🌐 Çevir",
        "btn_article": "📄 Makale",
        "btn_quotes": "💬 Anahtar alıntılar",
        "btn_script": "📝 Senaryo",
        "btn_save_content": "💾 Bunu kaydet",
        "no_video": "Son video bulunamadı. Önce bir YouTube veya TikTok bağlantısı gönderin.",
        "err_analysis": "Analiz oluşturulamadı.",
        "err_steps": "Adım bulunamadı.",
        "err_quotes": "Alıntı çıkarılamadı.",
        "err_content_plan": "İçerik planı oluşturulamadı.",
        "err_post": "Gönderi oluşturulamadı.",
        "err_article": "Makale oluşturulamadı.",
        "err_script": "Senaryo oluşturulamadı.",
        "err_summary": "Özetlenemedi.",
        "err_translate": "Çevrilemedi.",
        "saved_title": "Video belleğe kaydedildi:",
        "saved_content_title": "Belleğe kaydedildi.",
        "saved_note": "Daha sonra bana sorabilirsiniz.",
        "remind_prompt": "Bu videoyu ne zaman izlemek için hatırlatayım?",
        "remind_hint": (
            'Bir zaman ile cevap verin, ör. <b>«2 saat sonra hatırlat»</b> '
            'veya <b>«yarın saat 9»</b>'
        ),
        "similar_title": "Benzer videolar için:",
    },
    "it": {
        "btn_content_plan": "📋 Piano contenuti",
        "btn_post": "📝 Post",
        "btn_steps": "📌 Passi",
        "btn_save": "💾 Salva",
        "btn_remind": "⏰ Ricordami",
        "btn_similar": "🔍 Simili",
        "btn_deeper": "📖 Più dettagli",
        "btn_translate": "🌐 Traduci",
        "btn_article": "📄 Articolo",
        "btn_quotes": "💬 Citazioni chiave",
        "btn_script": "📝 Sceneggiatura",
        "btn_save_content": "💾 Salva questo",
        "no_video": "Nessun video recente. Invia prima un link YouTube o TikTok.",
        "err_analysis": "Impossibile generare l'analisi.",
        "err_steps": "Nessun passo trovato.",
        "err_quotes": "Nessuna citazione estratta.",
        "err_content_plan": "Impossibile generare il piano dei contenuti.",
        "err_post": "Impossibile generare il post.",
        "err_article": "Impossibile generare l'articolo.",
        "err_script": "Impossibile generare la sceneggiatura.",
        "err_summary": "Impossibile riassumere.",
        "err_translate": "Impossibile tradurre.",
        "saved_title": "Video salvato in memoria:",
        "saved_content_title": "Salvato in memoria.",
        "saved_note": "Puoi chiedermi di esso più tardi.",
        "remind_prompt": "Quando vuoi essere ricordato di guardare questo video?",
        "remind_hint": (
            'Rispondi con un orario, es. <b>«ricordami tra 2 ore»</b> '
            'o <b>«domani alle 9»</b>'
        ),
        "similar_title": "Video simili per:",
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
    """Normalize language code to a supported key, fallback to 'en'."""
    lang = (language or "en")[:2].lower()
    return lang if lang in _STRINGS else "en"


def t(key: str, language: str) -> str:
    """Translate a video_action string."""
    lang = _lang(language)
    return _STRINGS[lang].get(key, _STRINGS["en"].get(key, key))


def get_video_buttons(language: str) -> list[dict]:
    """Return localized video action buttons."""
    lang = _lang(language)
    strings = _STRINGS[lang]
    en_strings = _STRINGS["en"]
    return [
        {"text": strings.get(k, en_strings[k]), "callback": cb}
        for k, cb in _BUTTON_KEYS
    ]


def get_writing_buttons(language: str) -> list[dict]:
    """Return localized writing follow-up buttons (used after post generation)."""
    lang = _lang(language)
    strings = _STRINGS[lang]
    en_strings = _STRINGS["en"]
    return [
        {"text": strings.get(k, en_strings[k]), "callback": cb}
        for k, cb in _WRITING_BUTTON_KEYS
    ]
