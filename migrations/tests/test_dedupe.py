from shared.dedupe import compute_dedupe_hash, media_fingerprint, text_fingerprint


def test_text_fingerprint_normalizes_whitespace_and_case():
    a = text_fingerprint("Hello   World\n\nFoo")
    b = text_fingerprint("hello world foo")
    assert a == b


def test_text_fingerprint_empty():
    assert text_fingerprint(None) == text_fingerprint("")
    assert text_fingerprint("") == text_fingerprint("   ")


def test_media_fingerprint_stable_regardless_of_order():
    refs_a = [
        {"type": "photo", "file": "/media/a.jpg", "size": 100},
        {"type": "video", "file": "/media/b.mp4", "size": 5000},
    ]
    refs_b = list(reversed(refs_a))
    assert media_fingerprint(refs_a) == media_fingerprint(refs_b)


def test_compute_dedupe_hash_is_deterministic():
    h1 = compute_dedupe_hash("Some post", [{"type": "photo", "file": "x", "size": 1}])
    h2 = compute_dedupe_hash("Some post", [{"type": "photo", "file": "x", "size": 1}])
    assert h1 == h2
    assert len(h1) == 64


def test_compute_dedupe_hash_differs_on_text():
    h1 = compute_dedupe_hash("post A", None)
    h2 = compute_dedupe_hash("post B", None)
    assert h1 != h2


def test_compute_dedupe_hash_differs_on_media():
    h1 = compute_dedupe_hash("post", [{"type": "photo", "file": "a", "size": 1}])
    h2 = compute_dedupe_hash("post", [{"type": "video", "file": "b", "size": 2}])
    assert h1 != h2
