import hashlib
import re
import unicodedata

def clean_text(text):
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()

def normalize_key(text):
    text = clean_text(text).lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()

def fingerprint(*parts):
    raw = " | ".join(normalize_key(p) for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

def contains_here_we_go(text):
    return bool(re.search(r"\bhere\s+we\s+go\b", clean_text(text), re.I))

def name_match(name, text):
    """Word-boundary, case-insensitive check that `name` appears as a whole
    token sequence in `text` — not merely as a substring. Prevents a short
    name/alias like "Leo" from matching inside an unrelated word like
    "Leonardo", which a plain substring check would allow.
    """
    if not name or not text:
        return False
    pattern = r"\b" + re.escape(clean_text(name)).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text, re.I))

