"""Deterministic editorial analysis for football news and transfers.

The scores in this module are transparency indicators, not probability claims.
They describe how complete and actionable the supplied structured data is.
"""


_NEWS_IMPORTANCE = {
    "انتقال": "عالية",
    "إعارة": "عالية",
    "تعيين مدرب": "عالية",
    "إقالة مدرب": "عالية",
    "استحواذ": "عالية",
    "بيع أصول": "متوسطة",
    "تجديد عقد": "متوسطة",
    "إصابة": "متوسطة",
    "عودة من إصابة": "متوسطة",
    "اعتزال": "متوسطة",
}

_TRANSFER_TYPES = {"انتقال", "إعارة"}


def _clean(value):
    return str(value).strip() if value else ""


def analyze_news_event(event, item=None):
    """Return a compact, explainable analysis block for a structured article."""
    event = event or {}
    item = item or {}
    event_type = _clean(event.get("type")) or "خبر كرة قدم"
    entity_type = _clean(event.get("entity_type")) or "غير محدد"
    player = _clean(event.get("player"))
    frm = _clean(event.get("from"))
    to = _clean(event.get("to"))
    title = _clean(item.get("title"))
    source = _clean(item.get("source"))

    score = 20
    signals = ["تم تصنيف الخبر كحدث كروي منظم"]
    if event_type in _NEWS_IMPORTANCE:
        score += 20
        signals.append("نوع الحدث معروف")
    if entity_type in {"player", "club", "manager"}:
        score += 15
        signals.append("نوع الكيان محدد")
    if player or entity_type in {"club", "manager"}:
        score += 15
        signals.append("الطرف الرئيسي محدد")
    if event_type in _TRANSFER_TYPES and frm and to:
        score += 20
        signals.append("النادي السابق والوجهة محددان")
    elif event_type not in _TRANSFER_TYPES and frm:
        score += 15
        signals.append("النادي أو الجهة المرتبطة محددة")
    if title:
        score += 5
    if source:
        score += 5
    score = min(score, 100)

    if event_type in _TRANSFER_TYPES and player:
        summary = f"{event_type}: {player} من {frm or 'نادٍ غير محدد'} إلى {to or 'وجهة غير محددة'}."
    elif player:
        summary = f"{event_type}: {player}{f' مع {frm}' if frm else ''}."
    elif to:
        summary = f"{event_type}: {frm or 'جهة غير محددة'} إلى {to}."
    else:
        summary = f"{event_type} مرتبط بـ {frm or 'جهة غير محددة'}."

    return {
        "category": event_type,
        "event": {
            "type": event_type,
            "from": frm or None,
            "to": to or None,
            "player": player or None,
            "entity_type": entity_type,
        },
        "importance": _NEWS_IMPORTANCE.get(event_type, "منخفضة"),
        "completeness_score": score,
        "summary": summary,
        "signals": signals,
        "source": source or None,
        "title": title or None,
    }


def analyze_transfer(transfer, status=None):
    """Return a status/risk analysis for a Fabrizio transfer candidate."""
    transfer = transfer or {}
    status = status or transfer.get("status") or "WAITING_OFFICIAL"
    player = _clean(transfer.get("player")) or "لاعب غير محدد"
    frm = _clean(transfer.get("from_club"))
    to = _clean(transfer.get("to_club")) or "نادٍ غير محدد"
    stage = {
        "OFFICIAL": "رسمي",
        "HERE_WE_GO": "Here We Go غير رسمي بعد",
        "WAITING_OFFICIAL": "بانتظار التأكيد الرسمي",
    }.get(status, status)
    score = {"OFFICIAL": 100, "HERE_WE_GO": 75, "WAITING_OFFICIAL": 60}.get(status, 50)

    if status == "OFFICIAL":
        risk = "منخفض بعد توثيق إعلان النادي"
        recommendation = "يمكن نشرها كبطاقة رسمية."
    elif status == "HERE_WE_GO":
        risk = "متوسط؛ الإعلان الرسمي لم يصدر بعد"
        recommendation = "تُنشر بوسم Here We Go فقط، مع انتظار تأكيد رسمي ودون تقديمها كإعلان رسمي."
    else:
        risk = "مرتفع نسبيًا حتى ظهور دليل رسمي"
        recommendation = "تُتابع ولا تُحوّل إلى بطاقة نهائية قبل اكتمال التحقق."

    summary = f"{player} {f'من {frm} ' if frm else ''}إلى {to} — المرحلة: {stage}."
    return {
        "category": "تحليل صفقة",
        "stage": stage,
        "status": status,
        "status_score": score,
        "risk": risk,
        "recommendation": recommendation,
        "summary": summary,
    }
