"""Dedupe-hash computation for the lookback-window duplicate check.

The hash is keyed on the normalized text + a stable fingerprint of the media set
(plan §6: "keyed on normalized-text hash + media hash").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from shared.enums import MediaType


def text_fingerprint(normalized_text: str | None) -> str:
    """Normalize whitespace then sha256 the text."""
    cleaned = " ".join((normalized_text or "").split()).strip().lower()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def media_fingerprint(media_refs: list[dict]) -> str:
    """Stable fingerprint of a media set.

    `media_refs` items look like ``{"type": MediaType, "file": "/media/<uuid>", ...}``.
    Only content-stable fields are hashed (type + size + mime) so that identical
    content downloaded to different per-post paths still dedupes. The local
    ``file`` path is intentionally excluded — it is unique per post and would
    make every media-bearing post fingerprint distinct.

    Note: when ``size`` is unknown (e.g. some standalone photos), this falls back
    to type/mime only, which can collide for distinct media of the same type.
    """
    parts: list[str] = []
    for ref in sorted(media_refs, key=lambda r: (r.get("type", ""), r.get("size") or 0)):
        mtype = ref.get("type", "")
        size = ref.get("size") or 0
        mime = ref.get("mime") or ""
        parts.append(f"{mtype}:{size}:{mime}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def compute_dedupe_hash(normalized_text: str | None, media_refs: list[dict] | None) -> str:
    """Combine text + media fingerprints into a single dedupe key."""
    return hashlib.sha256(
        (text_fingerprint(normalized_text) + ":" + media_fingerprint(media_refs or [])).encode(
            "utf-8"
        )
    ).hexdigest()


def local_media_path(media_dir: str, post_id: int, index: int, ext: str, mtype: MediaType) -> Path:
    """Deterministic media path under the media volume."""
    safe_ext = ext.lstrip(".").lower() or "bin"
    return Path(media_dir) / f"{post_id}_{index}_{mtype.value}.{safe_ext}"
