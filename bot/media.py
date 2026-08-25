"""Reliable media selection for Telegram football-news posts.

Source images remain the first choice. Wikimedia is queried only when the
source image is absent or fails a deterministic quality check, and only for a
uniquely matched football player or manager.
"""

from __future__ import annotations

from html import unescape
from io import BytesIO
import re
import unicodedata

import requests
from PIL import Image, UnidentifiedImageError


_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
_PERSON_ENTITY_TYPES = {"player", "manager"}
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"


class NewsImageSelector:
    """Select a publishable source image or a safely matched Commons fallback."""

    def __init__(
        self,
        timeout=12,
        user_agent="TransferConfirmationBot/5.0",
        min_short_edge=640,
        min_pixels=600000,
        max_download_bytes=8_000_000,
        wikimedia_enabled=True,
        wikimedia_thumbnail_width=960,
    ):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}
        self.min_short_edge = max(1, int(min_short_edge))
        self.min_pixels = max(1, int(min_pixels))
        self.max_download_bytes = max(1, int(max_download_bytes))
        self.wikimedia_enabled = bool(wikimedia_enabled)
        self.wikimedia_thumbnail_width = max(320, int(wikimedia_thumbnail_width))

    def select(self, source_url, person=None, entity_type=None):
        """Return media metadata, preferring a good source image.

        A ``None`` result is deliberate: publishing a text-only post is safer
        than attaching an unclear image to an unrelated person or team.
        """
        source = self._source_media(source_url)
        if source:
            return source
        if not self.wikimedia_enabled or entity_type not in _PERSON_ENTITY_TYPES or not person:
            return None
        return self._wikimedia_media(person)

    def _source_media(self, url):
        if not self._http_url(url):
            return None
        if not self._is_usable_image(url):
            return None
        return {"url": url, "source": "source"}

    def _wikimedia_media(self, person):
        entity_id = self._wikidata_entity_id(person)
        if not entity_id:
            return None
        file_name = self._entity_image_file(entity_id)
        if not file_name:
            return None
        return self._commons_file_media(file_name)

    def _wikidata_entity_id(self, person):
        data = self._get_json(
            _WIKIDATA_API,
            {
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "uselang": "en",
                "type": "item",
                "limit": 5,
                "search": person,
            },
        )
        if not data:
            return None
        matches = []
        for candidate in data.get("search", []):
            label = candidate.get("label") or candidate.get("display", {}).get("label", {}).get("value")
            description = candidate.get("description") or candidate.get("display", {}).get("description", {}).get("value")
            if not candidate.get("id") or self._normalized_name(label) != self._normalized_name(person):
                continue
            if self._is_football_description(description):
                matches.append(candidate["id"])
        # Reject ambiguous names instead of risking a photograph of a different
        # football professional with the same name.
        return matches[0] if len(matches) == 1 else None

    def _entity_image_file(self, entity_id):
        data = self._get_json(
            _WIKIDATA_API,
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": entity_id,
                "props": "claims",
            },
        )
        try:
            claims = data["entities"][entity_id]["claims"]
            return claims["P18"][0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError, TypeError):
            return None

    def _commons_file_media(self, file_name):
        data = self._get_json(
            _COMMONS_API,
            {
                "action": "query",
                "format": "json",
                "titles": f"File:{file_name}",
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": self.wikimedia_thumbnail_width,
            },
        )
        if not data:
            return None
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values() if isinstance(pages, dict) else pages:
            try:
                image = page["imageinfo"][0]
                url = image["thumburl"]
            except (KeyError, IndexError, TypeError):
                continue
            if not self._is_usable_image(url):
                continue
            metadata = image.get("extmetadata", {})
            credit = self._metadata_text(metadata, "Attribution") or self._metadata_text(metadata, "Artist")
            license_name = self._metadata_text(metadata, "LicenseShortName")
            return {
                "url": url,
                "source": "wikimedia",
                "credit_name": credit or "Wikimedia Commons",
                "credit_license": license_name,
                "credit_url": image.get("descriptionurl"),
            }
        return None

    def _is_usable_image(self, url):
        info = self._probe_image(url)
        if not info or info["format"] not in _IMAGE_FORMATS:
            return False
        width, height = info["width"], info["height"]
        return min(width, height) >= self.min_short_edge and width * height >= self.min_pixels

    def _probe_image(self, url):
        response = None
        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].casefold()
            if content_type and not content_type.startswith("image/"):
                return None
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > self.max_download_bytes:
                return None
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) > self.max_download_bytes:
                    return None
            if not payload:
                return None
            with Image.open(BytesIO(payload)) as image:
                width, height = image.size
                image_format = image.format
                image.verify()
            return {"width": width, "height": height, "format": image_format}
        except (OSError, ValueError, requests.RequestException, UnidentifiedImageError, Image.DecompressionBombError):
            return None
        finally:
            if response is not None:
                response.close()

    def _get_json(self, endpoint, params):
        try:
            response = requests.get(endpoint, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except (ValueError, requests.RequestException):
            return None

    @staticmethod
    def _http_url(url):
        return isinstance(url, str) and url.startswith(("https://", "http://"))

    @staticmethod
    def _normalized_name(value):
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        normalized = "".join(char if char.isalnum() or char.isspace() else " " for char in normalized)
        return " ".join(normalized.casefold().split())

    @staticmethod
    def _is_football_description(description):
        description = " ".join(str(description or "").casefold().split())
        if "american football" in description:
            return False
        return any(term in description for term in ("footballer", "football player", "football manager", "soccer"))

    @staticmethod
    def _metadata_text(metadata, key):
        value = metadata.get(key, {}) if isinstance(metadata, dict) else {}
        value = value.get("value") if isinstance(value, dict) else value
        value = re.sub(r"<[^>]+>", " ", unescape(str(value or "")))
        return " ".join(value.split()) or None
