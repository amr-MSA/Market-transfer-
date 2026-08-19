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
}


def _text(value, fallback=""):
    return escape(str(value if value is not None else fallback), quote=False)


def _url(value):
    return escape(str(value or ""), quote=True)


def _analysis_block(analysis):
    if not analysis:
        return ""
    lines = []
    if analysis.get("stage"):
        lines.append(f"المرحلة: {_text(analysis['stage'])}")
    if analysis.get("category"):
        lines.append(f"التصنيف: {_text(analysis['category'])}")
    if analysis.get("importance"):
        lines.append(f"الأهمية: {_text(analysis['importance'])}")
    if analysis.get("risk"):
        lines.append(f"المخاطر: {_text(analysis['risk'])}")
    if analysis.get("recommendation"):
        lines.append(f"القراءة: {_text(analysis['recommendation'])}")
    if analysis.get("completeness_score") is not None:
        lines.append(f"اكتمال البيانات: {int(analysis['completeness_score'])}/100")
    if not lines:
        return ""
    return "\n\n📊 <b>تحليل سريع</b>\n" + "\n".join(lines)


def official_message(player, frm, to, url, analysis=None):
    player = _text(player)
    move = f"{_text(frm)} → {_text(to)}" if frm else f"→ {_text(to)}"
    return (
        f"🟢 <b>رسمي | {player}</b>\n\n"
        f"🔁 {move}\n\n"
        "تم تأكيد الصفقة رسمياً من النادي."
        f"{_analysis_block(analysis)}\n🔗 {_url(url)}"
    )


def here_we_go_message(player, frm, to, url, analysis=None):
    player = _text(player)
    move = f"{_text(frm)} → {_text(to)}" if frm else f"→ {_text(to)}"
    return (
        f"🟡 <b>Here We Go | {player}</b>\n\n"
        f"🔁 {move}\n\n"
        "فابريزيو رومانو أكد الصفقة، لكن الإعلان الرسمي لم يصدر بعد."
        f"{_analysis_block(analysis)}\n🔗 {_url(url)}"
    )


def football_news_message(item, analysis=None):
    item = item or {}
    title = _text(item.get("title"), "خبر كرة قدم")
    source = _text(item.get("source"), "مصدر إخباري")
    url = _url(item.get("url"))
    block = _analysis_block(analysis)
    content_type = analysis.get("category") if analysis else None
    type_icon = _CONTENT_TYPE_ICONS.get(content_type, "📰")
    category_line = f"{type_icon} <b>{_text(content_type)}</b>\n" if content_type else ""
    summary = _text(analysis.get("summary")) if analysis and analysis.get("summary") else ""
    summary_line = f"\n\n{summary}" if summary else ""
    return (
        f"{category_line}<b>{title}</b>{summary_line}\n\n"
        f"المصدر: {source}{block}\n"
        f"🔗 {url}"
    )
