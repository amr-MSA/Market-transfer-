from html import escape

_CONTENT_TYPE_ICONS = {
    "انتقال": "🔁",
    "إعارة": "↔️",
    "هدف": "⚽",
    "نتيجة": "📣",
    "مباراة": "🏟️",
    "إصابة": "🩺",
    "عودة من إصابة": "💪",
    "تجديد عقد": "✍️",
    "تعيين مدرب": "🧠",
    "إقالة مدرب": "🚪",
    "اعتزال": "🏁",
    "انتقال إداري": "🏢",
    "استحواذ": "📊",
    "بيع أصول": "📉",
    "تصريح": "🎙️",
    "انضباط": "🟨",
    "أخبار ناد": "📰",
    "أخرى": "🗞️",
}


def _text(value, fallback=""):
    return escape(str(value if value is not None else fallback), quote=False)


def _url(value):
    return escape(str(value or ""), quote=True)


def _name(ar, original):
    ar = str(ar or "").strip()
    original = str(original or "").strip()
    if ar and original and original.casefold() not in ar.casefold():
        return f"{_text(ar)} ({_text(original)})"
    return _text(ar or original)


def _move_line(editorial=None, player=None, frm=None, to=None):
    editorial = editorial or {}
    player_line = _name(editorial.get("player_ar"), editorial.get("player_original"))
    from_line = _name(editorial.get("from_ar"), editorial.get("from_original"))
    to_line = _name(editorial.get("to_ar"), editorial.get("to_original"))
    player_line = player_line or _text(player)
    from_line = from_line or _text(frm)
    to_line = to_line or _text(to)
    if player_line and from_line and to_line:
        return f"{player_line} · {from_line} → {to_line}"
    if player_line and from_line:
        return f"{player_line} · {from_line}"
    return ""


def _editorial_body(editorial):
    editorial = editorial or {}
    lines = []
    headline = _text(editorial.get("headline"))
    lead = _text(editorial.get("lead"))
    detail = _text(editorial.get("detail"))
    if headline:
        lines.append(f"<b>{headline}</b>")
    if lead:
        lines.append(lead)
    if detail:
        lines.append(detail)
    return "\n".join(lines)


def _source_line(source, url):
    return f"🗞 <i>{_text(source, 'مصدر إخباري')}</i> · <a href=\"{_url(url)}\">المصدر</a>"


def _media_credit(media):
    if not isinstance(media, dict) or media.get("source") != "wikimedia":
        return ""
    label_parts = [_text(media.get("credit_name"), "Wikimedia Commons")]
    license_name = _text(media.get("credit_license"))
    if license_name:
        label_parts.append(license_name)
    label = " · ".join(label_parts)
    credit_url = media.get("credit_url")
    return f"📷 <a href=\"{_url(credit_url)}\">{label}</a>" if credit_url else f"📷 {label}"


def official_message(player, frm, to, url, analysis=None, editorial=None, media=None):
    body = _editorial_body(editorial)
    move = _move_line(editorial, player, frm, to)
    if not body:
        body = f"<b>{_text(player, 'لاعب')}</b>\nتم تأكيد انتقاله رسميًا إلى {_text(to, 'الوجهة الجديدة')} من جانب النادي."
    parts = ["🟢 <b>انتقال رسمي</b>", body]
    if not editorial and move:
        parts.insert(2, move)
    parts.append(f"✅ {_text('تأكيد رسمي من النادي')}")
    parts.append(_source_line("المصدر الرسمي", url))
    media_credit = _media_credit(media)
    if media_credit:
        parts.append(media_credit)
    return "\n".join(parts)


def here_we_go_message(player, frm, to, url, analysis=None, editorial=None, media=None):
    body = _editorial_body(editorial)
    move = _move_line(editorial, player, frm, to)
    if not body:
        body = f"<b>{_text(player, 'لاعب')}</b>\nتأكيد Here We Go من Fabrizio، بانتظار الإعلان الرسمي."
    parts = ["🟡 <b>Here We Go</b>", body]
    if not editorial and move:
        parts.insert(2, move)
    parts.append("⏳ الإعلان الرسمي لم يصدر بعد")
    parts.append(_source_line("Fabrizio Romano", url))
    media_credit = _media_credit(media)
    if media_credit:
        parts.append(media_credit)
    return "\n".join(parts)


def football_news_message(item, analysis=None, editorial=None, media=None):
    item = item or {}
    analysis = analysis or {}
    editorial = editorial or {}
    event_type = editorial.get("section") or analysis.get("category") or "أخرى"
    icon = _CONTENT_TYPE_ICONS.get(event_type, "🗞️")
    body = _editorial_body(editorial)
    if not body:
        title = _text(item.get("title"), "خبر كرة قدم")
        summary = _text(analysis.get("summary"), "تفاصيل الخبر في المصدر.")
        body = f"<b>{title}</b>\n{summary}"
    parts = [
        f"{icon} <b>{_text(event_type)}</b>",
        body,
        _source_line(item.get("source"), item.get("url")),
    ]
    media_credit = _media_credit(media)
    if media_credit:
        parts.append(media_credit)
    return "\n".join(parts)
