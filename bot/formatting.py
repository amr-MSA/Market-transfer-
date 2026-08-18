def official_message(player, frm, to, url):
    move = f"{frm} → {to}" if frm else f"→ {to}"
    return f"🟢 <b>رسمي | {player}</b>\n\n🔁 {move}\n\nتم تأكيد الصفقة رسمياً من النادي.\n🔗 {url}"

def here_we_go_message(player, frm, to, url):
    move = f"{frm} → {to}" if frm else f"→ {to}"
    return f"🟡 <b>Here We Go | {player}</b>\n\n🔁 {move}\n\nفابريزيو رومانو أكد الصفقة، لكن الإعلان الرسمي لم يصدر بعد.\n🔗 {url}"


def football_news_message(item):
    title = item.get("title") or "خبر كرة قدم"
    source = item.get("source") or "مصدر إخباري"
    url = item.get("url") or ""
    return (
        f"📰 <b>{title}</b>\n\n"
        f"المصدر: {source}\n"
        f"🔗 {url}"
    )
