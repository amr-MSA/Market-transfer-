"""Human review queue for automatically discovered images.

Automatic image discovery (source-article photo, Wikimedia portrait, club
crest/stadium fallback) is never published directly. Every candidate found
for a given transfer or news item is offered to the administrators as one
numbered batch; only an explicit numeric reply from an admin — or ``0`` for
"none of these are suitable" — turns a candidate into published media.

This module owns the persisted queue so that:
  * a review is created at most once per target (idempotent by
    ``target_type``/``target_id``), so a slow admin reply never causes the
    same batch to be re-created or re-sent;
  * only one batch is ever "SENT" (awaiting a reply) at a time;
  * a target whose review is still pending is never published, and once
    resolved it is never re-resolved or re-published.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


class ImageReviewStore:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def empty():
        return {"version": 1, "updated_at": None, "reviews": {}}

    def load(self):
        if not self.path.exists():
            return self.empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return self.empty()
        if not isinstance(data, dict) or not isinstance(data.get("reviews"), dict):
            return self.empty()
        data.setdefault("version", 1)
        data.setdefault("updated_at", None)
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _review_id(target_type, target_id):
        raw = f"{target_type}:{target_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def get_for_target(self, data, target_type, target_id):
        return data.get("reviews", {}).get(self._review_id(target_type, target_id))

    def create(self, data, target_type, target_id, person, entity_type, club, candidates):
        """Create (or return the existing) review for this target.

        Idempotent by ``(target_type, target_id)``: calling this again while
        a review already exists — regardless of its status — returns that
        same review untouched instead of creating a duplicate batch or
        resetting an answer the admin already gave.
        """
        review_id = self._review_id(target_type, target_id)
        reviews = data.setdefault("reviews", {})
        existing = reviews.get(review_id)
        if existing:
            return existing
        review = {
            "review_id": review_id,
            "target_type": target_type,
            "target_id": str(target_id),
            "person": person,
            "entity_type": entity_type,
            "club": club,
            "candidates": [
                {"code": index + 1, "label": candidate.get("label"), "media": candidate.get("media")}
                for index, candidate in enumerate(candidates)
            ],
            "status": "PENDING",
            "selected_code": None,
            "resolved_media": None,
            "message_ids": [],
            "created_at": self._now(),
            "sent_at": None,
            "resolved_at": None,
        }
        reviews[review_id] = review
        data["updated_at"] = self._now()
        return review

    def next_pending(self, data):
        """Return the oldest still-unsent review, or ``None``."""
        pending = [r for r in data.get("reviews", {}).values() if r.get("status") == "PENDING"]
        pending.sort(key=lambda r: r.get("created_at") or "")
        return pending[0] if pending else None

    def get_awaiting_reply(self, data):
        """Return the single review currently sent to the admin, if any."""
        for review in data.get("reviews", {}).values():
            if review.get("status") == "SENT":
                return review
        return None

    def mark_sent(self, data, review_id, message_ids):
        review = data.get("reviews", {}).get(review_id)
        if not review:
            return None
        review["status"] = "SENT"
        review["message_ids"] = list(message_ids or [])
        review["sent_at"] = self._now()
        data["updated_at"] = self._now()
        return review

    def resolve(self, data, review_id, code):
        """Apply the administrator's numeric reply to a SENT review.

        Returns the updated review on success, ``False`` when ``code`` does
        not match any candidate on this specific review (the caller should
        ask the admin to try again rather than silently drop the reply), or
        ``None`` when there is nothing awaiting a reply for this id.
        """
        review = data.get("reviews", {}).get(review_id)
        if not review or review.get("status") != "SENT":
            return None
        if code == 0:
            review["status"] = "NO_MATCH"
            review["selected_code"] = 0
            review["resolved_media"] = None
        else:
            match = next((c for c in review.get("candidates", []) if c.get("code") == code), None)
            if not match:
                return False
            review["status"] = "APPROVED"
            review["selected_code"] = code
            review["resolved_media"] = match.get("media")
        review["resolved_at"] = self._now()
        data["updated_at"] = self._now()
        return review

    def prune(self, data, retention_days=60, now=None):
        """Drop resolved (APPROVED/NO_MATCH) reviews older than the window.

        PENDING/SENT reviews are always kept regardless of age — they still
        need an administrator decision.
        """
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention_days)
        kept = {}
        for review_id, review in data.get("reviews", {}).items():
            if review.get("status") not in {"APPROVED", "NO_MATCH"}:
                kept[review_id] = review
                continue
            marker = review.get("resolved_at") or review.get("created_at")
            try:
                when = datetime.fromisoformat(str(marker).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                when = now  # malformed/missing timestamp: keep it, don't guess
            if when >= cutoff:
                kept[review_id] = review
        data["reviews"] = kept
        return data

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()
