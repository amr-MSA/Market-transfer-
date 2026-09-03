"""Reliable media selection for Telegram football-news posts.

Source images remain the first choice. Wikimedia is queried only when the
source image is absent or fails a deterministic quality check, and only for a
uniquely matched football player or manager.
"""

from __future__ import annotations

from html import unescape
from io import BytesIO
from pathlib import Path
import re
import unicodedata

import requests
from PIL import Image, UnidentifiedImageError

try:
    import numpy as np
    import mediapipe as mp
except ImportError:  # pragma: no cover - optional dependency, degrades safely
    np = None
    mp = None


_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
_PERSON_ENTITY_TYPES = {"player", "manager"}
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# MediaPipe Pose Landmarker indices for hips/knees/ankles. Any of these being
# visible in frame means the shot extends past the waist, so it is rejected
# as a proxy for "no knee or lower-body skin visible" — see
# ``_shows_lower_body`` for why a landmark-presence check is used instead of
# skin-vs-fabric classification.
_LOWER_BODY_LANDMARK_INDICES = (23, 24, 25, 26, 27, 28)
# The Tasks API (unlike the older bundled "solutions" API) ships no model
# weights in the pip package; the lite pose model (~5 MB) is fetched once and
# cached on disk. The CI workflow additionally caches this path across runs
# via actions/cache so a normal run never needs the network for it.
_POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
_POSE_MODEL_CACHE_PATH = Path.home() / ".cache" / "mediapipe-models" / "pose_landmarker_lite.task"


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
        modesty_pose_filter_enabled=True,
        modesty_pose_visibility_threshold=0.5,
    ):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}
        self.min_short_edge = max(1, int(min_short_edge))
        self.min_pixels = max(1, int(min_pixels))
        self.max_download_bytes = max(1, int(max_download_bytes))
        self.wikimedia_enabled = bool(wikimedia_enabled)
        self.wikimedia_thumbnail_width = max(320, int(wikimedia_thumbnail_width))
        # Requires the optional mediapipe/numpy dependencies; silently
        # disabled (never blocks publishing) when they are not installed.
        self.modesty_pose_filter_enabled = bool(modesty_pose_filter_enabled) and mp is not None
        self.modesty_pose_visibility_threshold = float(modesty_pose_visibility_threshold)
        self._pose_detector = None

    def select(self, source_url, person=None, entity_type=None, strict_modesty=False, club=None):
        """Return media metadata, preferring a good source image.

        A ``None`` result is deliberate: publishing a text-only post is safer
        than attaching an unclear image to an unrelated person or team.
        """
        if strict_modesty:
            return self.club_fallback(club)
        source = self._source_media(source_url)
        if source:
            return source
        if not self.wikimedia_enabled or entity_type not in _PERSON_ENTITY_TYPES or not person:
            return None
        return self._wikimedia_media(person)

    def candidates(self, source_url, person=None, entity_type=None, club=None, strict_modesty=False):
        """Return every distinct image worth offering an administrator.

        Unlike ``select``, this never auto-picks a winner: the source image,
        a uniquely matched Wikimedia portrait, and the safe club crest/
        stadium fallback are all surfaced together (when available) so a
        human makes the final call. Under ``strict_modesty`` only the club
        fallback is offered, matching the restriction ``select`` applies in
        that mode.
        """
        options = []
        if not strict_modesty:
            source = self._source_media(source_url)
            if source:
                options.append({"label": "صورة من مصدر الخبر", "media": source})
            if self.wikimedia_enabled and entity_type in _PERSON_ENTITY_TYPES and person:
                wikimedia = self._wikimedia_media(person)
                if wikimedia and not self._same_media(wikimedia, options):
                    options.append({"label": "صورة من Wikimedia Commons", "media": wikimedia})
        club_media = self.club_fallback(club)
        if club_media and not self._same_media(club_media, options):
            options.append({"label": "شعار/ملعب النادي (بديل آمن)", "media": club_media})
        return options

    @staticmethod
    def _same_media(candidate, existing_options):
        url = candidate.get("url")
        return any(option["media"].get("url") == url for option in existing_options)

    def club_fallback(self, club):
        """Return only a club crest or stadium visual, never an uncertain photo.

        P154 is a logo image. P18 is accepted only when its file name signals a
        non-person club/stadium visual; otherwise text-only is safer.
        """
        if not club:
            return None
        entity_id = self._club_entity_id(club)
        if not entity_id:
            return None
        logo = self._entity_image_file(entity_id, properties=("P154",))
        if logo:
            return self._commons_file_media(logo)
        image = self._entity_image_file(entity_id, properties=("P18",))
        if image and re.search(r"(?:logo|crest|badge|stadium|arena|ground|estadio|park)", image, re.I):
            return self._commons_file_media(image)
        return None

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

    def _club_entity_id(self, club):
        data = self._get_json(
            _WIKIDATA_API,
            {"action": "wbsearchentities", "format": "json", "language": "en", "uselang": "en", "type": "item", "limit": 5, "search": club},
        )
        matches = []
        for candidate in (data or {}).get("search", []):
            description = str(candidate.get("description") or "").casefold()
            label = candidate.get("label") or candidate.get("display", {}).get("label", {}).get("value")
            if candidate.get("id") and self._normalized_name(label) == self._normalized_name(club) and "football club" in description:
                matches.append(candidate["id"])
        return matches[0] if len(matches) == 1 else None

    def _entity_image_file(self, entity_id, properties=("P18",)):
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
            for prop in properties:
                if claims.get(prop):
                    return claims[prop][0]["mainsnak"]["datavalue"]["value"]
            return None
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
                "modesty_approved": False,
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
            # Two separate opens by design: verify() must run on a handle
            # that has had no other decoding performed on it, and the pose
            # check below needs actual pixel data (which verify() must not
            # see) from a second, fresh handle.
            with Image.open(BytesIO(payload)) as verify_handle:
                verify_handle.verify()
            with Image.open(BytesIO(payload)) as image:
                width, height = image.size
                image_format = image.format
                if self._shows_lower_body(image):
                    return None
            return {"width": width, "height": height, "format": image_format}
        except (OSError, ValueError, requests.RequestException, UnidentifiedImageError, Image.DecompressionBombError):
            return None
        finally:
            if response is not None:
                response.close()

    def _shows_lower_body(self, image):
        """Reject any photo where hips/knees/ankles are visibly in frame.

        Distinguishing bare skin from fabric reliably needs a heavier human-
        parsing model than fits a periodic CI job. Instead this uses a
        conservative proxy: if MediaPipe Pose Landmarker can locate the hip,
        knee, or ankle joints with reasonable confidence, the shot extends
        past the waist and is rejected outright — regardless of whether that
        area happens to be covered by clothing. Headshot/shoulders-up
        portraits (no lower-body landmarks in frame) pass through
        unaffected, and non-person images such as club crests or stadiums
        naturally have no landmarks at all.
        """
        if not self.modesty_pose_filter_enabled:
            return False
        detector = self._get_pose_detector()
        if detector is None:
            return False
        try:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image.convert("RGB")))
            result = detector.detect(mp_image)
        except Exception:
            # A detector failure should never block an otherwise-valid image
            # differently from "pose filtering unavailable" — fail open.
            return False
        for landmarks in getattr(result, "pose_landmarks", None) or []:
            for index in _LOWER_BODY_LANDMARK_INDICES:
                if index < len(landmarks) and landmarks[index].visibility >= self.modesty_pose_visibility_threshold:
                    return True
        return False

    def _get_pose_detector(self):
        if self._pose_detector is not None:
            return self._pose_detector
        if not self.modesty_pose_filter_enabled:
            return None
        model_bytes = self._load_pose_model_bytes()
        if not model_bytes:
            # Never let a missing/unreachable model silently block every
            # single image for the rest of this run.
            self.modesty_pose_filter_enabled = False
            return None
        try:
            options = mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=model_bytes),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
            )
            self._pose_detector = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        except Exception:
            self.modesty_pose_filter_enabled = False
            self._pose_detector = None
        return self._pose_detector

    def _load_pose_model_bytes(self):
        try:
            if _POSE_MODEL_CACHE_PATH.exists():
                return _POSE_MODEL_CACHE_PATH.read_bytes()
        except OSError:
            pass
        try:
            response = requests.get(_POSE_MODEL_URL, timeout=max(self.timeout, 15))
            response.raise_for_status()
            data = response.content
        except (OSError, requests.RequestException):
            return None
        try:
            _POSE_MODEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _POSE_MODEL_CACHE_PATH.write_bytes(data)
        except OSError:
            pass  # a failed cache write shouldn't stop us from using the bytes now
        return data

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
