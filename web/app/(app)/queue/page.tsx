"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Paginated, Post, PostState, Tag } from "@/lib/types";

const PAGE_SIZE = 50;
const STATE_FILTERS: PostState[] = [
  "pending",
  "approved",
  "scheduled",
  "publishing",
  "published",
  "rejected",
  "publish_failed",
];

export default function QueuePage() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [filter, setFilter] = useState<PostState>("pending");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch a page and either replace or append to the current list.
  const fetchPage = useCallback(
    async (pageOffset: number, append: boolean) => {
      try {
        const data = await apiFetch<Paginated<Post>>(
          `/queue?state=${filter}&limit=${PAGE_SIZE}&offset=${pageOffset}`,
        );
        setPosts((prev) => (append ? [...prev, ...data.items] : data.items));
        setTotal(data.total);
        setOffset(pageOffset + data.items.length);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    },
    [filter],
  );

  // Full refresh (state filter changed or post action taken).
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    await fetchPage(0, false);
    setLoading(false);
  }, [fetchPage]);

  // Load the next page without resetting the list.
  const loadMore = async () => {
    setLoadingMore(true);
    await fetchPage(offset, true);
    setLoadingMore(false);
  };

  useEffect(() => {
    apiFetch<Tag[]>("/tags")
      .then(setTags)
      .catch(() => {});
  }, []);

  useEffect(() => {
    // Reset pagination whenever the filter changes.
    setOffset(0);
    setPosts([]);
    refresh();
  }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (
    post: Post,
    action: string,
    body?: Record<string, unknown>,
  ) => {
    try {
      await apiFetch<Post>(`/queue/${post.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ action, ...body }),
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  };

  const hasMore = posts.length < total;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">
          Draft queue
          {total > 0 && (
            <span className="ml-2 text-sm font-normal text-slate-500">
              ({total})
            </span>
          )}
        </h1>
        <div className="flex flex-wrap gap-1">
          {STATE_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`rounded px-2 py-1 text-xs ${
                filter === s
                  ? "bg-slate-800 text-white"
                  : "bg-white text-slate-600 hover:bg-slate-100"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      {loading ? (
        <div className="text-slate-400">Loading…</div>
      ) : posts.length === 0 ? (
        <div className="text-slate-400">No posts in this state.</div>
      ) : (
        <>
          <div className="grid gap-3">
            {posts.map((p) => (
              <QueueCard key={p.id} post={p} tags={tags} onAct={act} />
            ))}
          </div>
          {hasMore && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              className="w-full rounded border border-slate-300 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              {loadingMore
                ? "Loading…"
                : `Load more (${total - posts.length} remaining)`}
            </button>
          )}
        </>
      )}
    </div>
  );
}

function QueueCard({
  post,
  tags,
  onAct,
}: {
  post: Post;
  tags: Tag[];
  onAct: (
    post: Post,
    action: string,
    body?: Record<string, unknown>,
  ) => Promise<void>;
}) {
  // Keep `selected` in sync with the post's current tag_ids whenever the post
  // object is replaced (e.g. after a refresh), instead of keeping the initial
  // snapshot from the first render.
  const [selected, setSelected] = useState<number[]>(post.tag_ids);
  const prevPostId = useRef(post.id);
  useEffect(() => {
    // Re-initialise only when the post identity or its tag set changes.
    if (
      post.id !== prevPostId.current ||
      post.tag_ids.join(",") !== selected.join(",")
    ) {
      setSelected(post.tag_ids);
      prevPostId.current = post.id;
    }
  }, [post.id, post.tag_ids]); // eslint-disable-line react-hooks/exhaustive-deps

  const [schedAt, setSchedAt] = useState("");
  const [showTags, setShowTags] = useState(false);
  const [showSched, setShowSched] = useState(false);

  const toggle = (id: number) =>
    setSelected((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : [...s, id],
    );

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span>
          #{post.id} · src msg {post.source_message_id} · channel{" "}
          {post.source_channel_id}
        </span>
        <span className="rounded bg-slate-100 px-2 py-0.5 font-medium uppercase">
          {post.state}
        </span>
      </div>
      <pre className="whitespace-pre-wrap break-words rounded bg-slate-50 p-3 text-sm">
        {post.normalized_text || post.raw_text || "(empty)"}
      </pre>
      {post.raw_media_refs?.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          media: {post.raw_media_refs.map((m) => m.type).join(", ")}
          {post.raw_media_refs.some((m) => m.omitted) &&
            " (some omitted: too large)"}
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          onClick={() => onAct(post, "approve", { tag_ids: selected })}
          className="rounded bg-green-600 px-3 py-1 text-sm text-white hover:bg-green-700"
        >
          Approve
        </button>
        <button
          onClick={() => onAct(post, "reject")}
          className="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
        >
          Reject
        </button>
        <button
          onClick={() => setShowTags((v) => !v)}
          className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
        >
          {showTags ? "Hide tags" : `Tags (${selected.length})`}
        </button>
        <button
          onClick={() => setShowSched((v) => !v)}
          className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
        >
          Schedule
        </button>
      </div>

      {showTags && (
        <div className="mt-3 flex flex-wrap gap-2">
          {tags.map((t) => (
            <button
              key={t.id}
              onClick={() => toggle(t.id)}
              className={`rounded-full border px-2 py-0.5 text-xs ${
                selected.includes(t.id)
                  ? "border-slate-800 bg-slate-800 text-white"
                  : "border-slate-300 text-slate-600"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {showSched && (
        <div className="mt-3 flex items-center gap-2">
          <input
            type="datetime-local"
            value={schedAt}
            onChange={(e) => setSchedAt(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button
            onClick={() =>
              schedAt &&
              onAct(post, "schedule", {
                tag_ids: selected,
                scheduled_for: new Date(schedAt).toISOString(),
              })
            }
            className="rounded bg-slate-800 px-3 py-1 text-sm text-white hover:bg-slate-700"
          >
            Schedule
          </button>
        </div>
      )}
    </div>
  );
}
