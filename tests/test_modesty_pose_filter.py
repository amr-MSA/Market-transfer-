from io import BytesIO

from PIL import Image

from bot.media import NewsImageSelector


class _FakeLandmark:
    def __init__(self, visibility):
        self.visibility = visibility


class _FakeResult:
    def __init__(self, pose_landmarks):
        self.pose_landmarks = pose_landmarks


class _FakeDetector:
    def __init__(self, pose_landmarks):
        self._pose_landmarks = pose_landmarks

    def detect(self, mp_image):
        return _FakeResult(self._pose_landmarks)


class _BrokenDetector:
    def detect(self, mp_image):
        raise RuntimeError("model failure")


def _blank_image():
    return Image.new("RGB", (200, 200), color=(120, 120, 120))


def _full_body_landmarks():
    # 33 MediaPipe Pose landmarks, all confidently visible (hips/knees/ankles
    # included among indices 23-28).
    return [_FakeLandmark(0.9) for _ in range(33)]


def _headshot_landmarks():
    # Face/shoulder landmarks confidently visible; hip/knee/ankle landmarks
    # (indices 23-28) below the visibility threshold, as in a tight crop.
    return [_FakeLandmark(0.9) for _ in range(23)] + [_FakeLandmark(0.05) for _ in range(10)]


def test_full_body_photo_is_rejected():
    selector = NewsImageSelector(modesty_pose_filter_enabled=True)
    selector._pose_detector = _FakeDetector([_full_body_landmarks()])

    assert selector._shows_lower_body(_blank_image()) is True


def test_headshot_is_accepted():
    selector = NewsImageSelector(modesty_pose_filter_enabled=True)
    selector._pose_detector = _FakeDetector([_headshot_landmarks()])

    assert selector._shows_lower_body(_blank_image()) is False


def test_image_with_no_detected_person_is_accepted():
    # Club crests, stadium photos, etc. naturally have no pose landmarks.
    selector = NewsImageSelector(modesty_pose_filter_enabled=True)
    selector._pose_detector = _FakeDetector([])

    assert selector._shows_lower_body(_blank_image()) is False


def test_disabled_filter_never_calls_the_detector():
    selector = NewsImageSelector(modesty_pose_filter_enabled=False)
    selector._pose_detector = _FakeDetector([_full_body_landmarks()])

    assert selector._shows_lower_body(_blank_image()) is False


def test_detector_failure_fails_open():
    # A crashing model must never block an otherwise-valid image differently
    # from "pose filtering unavailable" — publishing degrades safely.
    selector = NewsImageSelector(modesty_pose_filter_enabled=True)
    selector._pose_detector = _BrokenDetector()

    assert selector._shows_lower_body(_blank_image()) is False


def test_unreachable_model_download_disables_the_filter_gracefully(monkeypatch, tmp_path):
    import bot.media as media_module

    monkeypatch.setattr(media_module, "_POSE_MODEL_CACHE_PATH", tmp_path / "missing" / "pose.task")

    def fake_get(url, timeout=None):
        raise media_module.requests.RequestException("network unavailable")

    monkeypatch.setattr(media_module.requests, "get", fake_get)

    selector = NewsImageSelector(modesty_pose_filter_enabled=True)

    assert selector._get_pose_detector() is None
    assert selector.modesty_pose_filter_enabled is False


def test_cached_model_bytes_are_reused_without_a_download(monkeypatch, tmp_path):
    import bot.media as media_module

    cache_path = tmp_path / "pose.task"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"fake-model-bytes")
    monkeypatch.setattr(media_module, "_POSE_MODEL_CACHE_PATH", cache_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not re-download a cached model")

    monkeypatch.setattr(media_module.requests, "get", fail_if_called)

    selector = NewsImageSelector(modesty_pose_filter_enabled=True)

    assert selector._load_pose_model_bytes() == b"fake-model-bytes"


def test_full_body_source_image_is_rejected_by_probe(monkeypatch):
    # End-to-end through _probe_image: a technically valid, high-resolution
    # JPEG is still rejected once the (mocked) pose detector finds knees.
    selector = NewsImageSelector(min_short_edge=10, min_pixels=100, modesty_pose_filter_enabled=True)
    selector._pose_detector = _FakeDetector([_full_body_landmarks()])

    buffer = BytesIO()
    Image.new("RGB", (800, 800), color=(200, 50, 50)).save(buffer, format="JPEG")
    payload = buffer.getvalue()

    class _Response:
        headers = {"Content-Type": "image/jpeg"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield payload

        def close(self):
            return None

    monkeypatch.setattr(
        "bot.media.requests.get",
        lambda url, headers, timeout, stream, allow_redirects: _Response(),
    )

    assert selector._is_usable_image("https://example.test/full-body.jpg") is False
