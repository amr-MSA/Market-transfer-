from .news_extractor import CONTENT_TYPES


ALL = "*"


def normalize_content_types(values):
    """Validate a channel's content subscriptions without silently guessing."""
    if values is None:
        return [ALL]  # Existing installations keep receiving everything.
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",")]
    if not isinstance(values, (list, tuple, set)):
        raise ValueError("content_types must be a list of content types")

    cleaned = []
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        if item in {ALL, "الكل", "all", "ALL"}:
            return [ALL]
        if item not in CONTENT_TYPES:
            raise ValueError(f"Unsupported content type: {item}")
        if item not in cleaned:
            cleaned.append(item)
    if not cleaned:
        raise ValueError("At least one content type is required")
    return cleaned


def channel_accepts(channel, content_type):
    if not channel.get("enabled", True):
        return False
    subscriptions = normalize_content_types(channel.get("content_types"))
    return ALL in subscriptions or content_type in subscriptions


def channels_for_content(channels, content_type):
    return [channel for channel in channels if channel_accepts(channel, content_type)]
