"""Unit tests for the deduplication logic in ``shared/dedupe.py``.

The hash is the mechanism that prevents a duplicate post from ever being sent to
Telegram: at normalize time a matching ``dedupe_hash`` short-circuits to
``rejected`` before any publish job is enqueued. These tests pin that behavior at
the hash level.
"""

from __future__ import annotations

import hashlib

from shared.dedupe import compute_dedupe_hash, local_media_path, media_fingerprint, text_fingerprint
from shared.enums import MediaType

_HEX64 = set("0123456789abcdef")


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(c in _HEX64 for c in value)


# ── text_fingerprint ──────────────────────────────────────────────────────────


def test_text_fingerprint_is_sha256_hex():
    assert _is_hex64(text_fingerprint("anything"))


def test_text_fingerprint_normalizes_whitespace_and_case():
    assert text_fingerprint("  Hello   World  ") == text_fingerprint("hello world")
    assert text_fingerprint("HELLO") == text_fingerprint("hello")


def test_text_fingerprint_none_equals_empty():
    assert text_fingerprint(None) == text_fingerprint("")
    assert text_fingerprint(None) == hashlib.sha256(b"").hexdigest()


def test_text_fingerprint_is_deterministic():
    assert text_fingerprint("same text") == text_fingerprint("same text")


# ── media_fingerprint ─────────────────────────────────────────────────────────


def test_media_fingerprint_empty_set():
    assert media_fingerprint([]) == hashlib.sha256(b"").hexdigest()


def test_media_fingerprint_is_order_invariant():
    a = [
        {"type": "photo", "size": 1024, "mime": "image/jpeg"},
        {"type": "video", "size": 5000, "mime": "video/mp4"},
    ]
    b = list(reversed(a))
    assert media_fingerprint(a) == media_fingerprint(b)


def test_media_fingerprint_ignores_local_file_path():
    """The per-post ``file`` path is excluded so identical content dedupes
    even when downloaded to different paths."""
    ref_a = {"type": "photo", "size": 1024, "mime": "image/jpeg", "file": "/media/1_0_photo.jpg"}
    ref_b = {"type": "photo", "size": 1024, "mime": "image/jpeg", "file": "/media/2_0_photo.jpg"}
    assert media_fingerprint([ref_a]) == media_fingerprint([ref_b])


def test_media_fingerprint_distinct_for_different_size():
    small = {"type": "photo", "size": 100, "mime": "image/jpeg"}
    large = {"type": "photo", "size": 999, "mime": "image/jpeg"}
    assert media_fingerprint([small]) != media_fingerprint([large])


def test_media_fingerprint_distinct_for_different_type():
    photo = {"type": "photo", "size": 1024, "mime": "image/jpeg"}
    video = {"type": "video", "size": 1024, "mime": "video/mp4"}
    assert media_fingerprint([photo]) != media_fingerprint([video])


# ── compute_dedupe_hash ───────────────────────────────────────────────────────


def test_dedupe_hash_is_hex64():
    assert _is_hex64(compute_dedupe_hash("text", []))


def test_dedupe_hash_combines_text_and_media_as_documented():
    text = "some post"
    media = [{"type": "photo", "size": 10, "mime": "image/jpeg"}]
    expected = hashlib.sha256(
        (text_fingerprint(text) + ":" + media_fingerprint(media)).encode("utf-8")
    ).hexdigest()
    assert compute_dedupe_hash(text, media) == expected


def test_dedupe_hash_is_keyed_on_raw_text_not_template():
    """Changing how text is rendered (template) does not change the dedupe key —
    the hash feeds on raw text + media, so old published content stays deduped."""
    raw = "Same source text"
    assert compute_dedupe_hash(raw, []) == compute_dedupe_hash(raw, [])


def test_identical_content_hashes_equal_duplicate_detection():
    raw = "Breaking: identical post"
    media = [{"type": "photo", "size": 2048, "mime": "image/png"}]
    assert compute_dedupe_hash(raw, media) == compute_dedupe_hash(raw, list(media))


def test_differing_text_or_media_hashes_differ():
    base = compute_dedupe_hash("post A", [])
    assert base != compute_dedupe_hash("post B", [])
    assert base != compute_dedupe_hash(
        "post A", [{"type": "photo", "size": 1, "mime": "image/jpeg"}]
    )


def test_dedupe_hash_none_inputs():
    assert _is_hex64(compute_dedupe_hash(None, None))
    assert compute_dedupe_hash(None, None) == compute_dedupe_hash("", [])


# ── local_media_path ──────────────────────────────────────────────────────────


def test_local_media_path_is_deterministic_and_normalized():
    p = local_media_path("/media", 7, 0, ".JPG", MediaType.photo)
    assert p == p
    assert p.name == "7_0_photo.jpg"
    assert p.parent.name == "media"


def test_local_media_path_empty_extension_falls_back_to_bin():
    p = local_media_path("/media", 7, 1, "", MediaType.document)
    assert p.name == "7_1_document.bin"


def test_local_media_path_strips_leading_dot():
    assert local_media_path("/m", 1, 0, ".mp4", MediaType.video).name == "1_0_video.mp4"
