"""Normalize job: deduplication routing, with the Telegram-publishing boundary
mocked (the ARQ ``enqueue_publish`` / ``enqueue_post_draft`` helpers).

The key assertion: a duplicate post is rejected and NEVER enqueues a publish —
publish is the only path that would touch Telegram, so mocking it proves dedupe
short-circuits before any message is sent.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.enums import Policy, PostState
from shared.models import Post, SourceChannel
from worker import normalize as norm_mod


def _make_post() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        state=PostState.pending,
        raw_text="Hello world",
        raw_media_refs=[],
        source_channel_id=10,
        normalized_text=None,
        tag_ids=[],
        media_paths=[],
        dedupe_hash=None,
    )


def _make_channel(policy: Policy) -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        policy=policy,
        # None -> worker uses DEFAULT_TEMPLATE_BODY (no Template row fetched).
        normalization_template_id=None,
        # [] -> resolve_tag_labels returns early without touching the DB.
        default_tag_ids=[],
        source_label="src",
        username=None,
        title="Src",
    )


class _FakeSession:
    """Minimal async session: supports the .get/.add/.commit the normalize job uses."""

    def __init__(self, post: SimpleNamespace, channel: SimpleNamespace) -> None:
        self._post = post
        self._channel = channel
        self.added: list[object] = []
        self.commits = 0

    async def get(self, cls, _ident):
        if cls is Post:
            return self._post
        if cls is SourceChannel:
            return self._channel
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class _SessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._s = session

    async def __aenter__(self) -> _FakeSession:
        return self._s

    async def __aexit__(self, *exc) -> bool:
        return False


@pytest.fixture
def patched(monkeypatch):
    post = _make_post()
    channel = _make_channel(Policy.queue)
    session = _FakeSession(post, channel)

    monkeypatch.setattr(norm_mod, "SessionLocal", lambda: _SessionCtx(session))
    publish = AsyncMock()
    draft = AsyncMock()
    monkeypatch.setattr(norm_mod, "enqueue_publish", publish)
    monkeypatch.setattr(norm_mod, "enqueue_post_draft", draft)
    is_dup = AsyncMock(return_value=False)
    monkeypatch.setattr(norm_mod, "_is_duplicate", is_dup)

    return SimpleNamespace(
        post=post,
        channel=channel,
        session=session,
        publish=publish,
        draft=draft,
        is_dup=is_dup,
    )


# ── pure routing decision ─────────────────────────────────────────────────────


def test_decide_route_duplicate_short_circuits():
    assert norm_mod.decide_route(Policy.auto, True) == "duplicate"
    assert norm_mod.decide_route(Policy.queue, True) == "duplicate"


def test_decide_route_non_duplicate_by_policy():
    assert norm_mod.decide_route(Policy.auto, False) == "publish"
    assert norm_mod.decide_route(Policy.queue, False) == "draft"


# ── normalize job with Telegram boundary mocked ───────────────────────────────


async def test_duplicate_is_rejected_and_never_published(patched):
    patched.is_dup.return_value = True

    result = await norm_mod.normalize({}, patched.post.id)

    assert result == "duplicate"
    assert patched.post.state == PostState.rejected
    patched.publish.assert_not_called()
    patched.draft.assert_not_called()
    assert patched.session.commits == 1
    assert len(patched.session.added) == 1  # the duplicate event


async def test_auto_channel_non_duplicate_enqueues_publish(patched):
    patched.channel.policy = Policy.auto

    result = await norm_mod.normalize({}, patched.post.id)

    assert result == "enqueued_publish"
    patched.publish.assert_awaited_once_with(patched.post.id)
    patched.draft.assert_not_called()
    # normalize does not flip state to approved; publish owns publishing->published.
    assert patched.post.state == PostState.pending
    assert patched.post.normalized_text is not None


async def test_queue_channel_non_duplicate_enqueues_draft(patched):
    result = await norm_mod.normalize({}, patched.post.id)

    assert result == "enqueued_draft"
    patched.draft.assert_awaited_once_with(patched.post.id)
    patched.publish.assert_not_called()
