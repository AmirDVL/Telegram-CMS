# Bot & Back-Office Guide

This guide covers day-to-day use of the Telegram CMS Bot for editors and admins — both the Telegram bot interface and the web back-office.

---

## Roles

Three roles exist. Roles are assigned in the web back-office under **Admins**.

| Role | Permissions |
|---|---|
| `editor` | View queue, approve, reject posts |
| `admin` | Everything an editor can do, plus full CRUD for tags, templates, and source channels |
| `super_admin` | Everything an admin can do, plus create, edit, and disable admin accounts |

---

## Linking Your Telegram Account

Inline approve/reject buttons in the editor supergroup only work if your Telegram user ID is linked to your web account. Without this link, button presses are silently rejected (a warning is logged, but no error is shown to you in Telegram).

**Steps:**

1. Find your numeric Telegram user ID. The bot [@userinfobot](https://t.me/userinfobot) will send it to you when you start a chat with it.
2. Ask a `super_admin` to go to the web back-office → **Admins** → edit your account → enter your Telegram user ID in the **Telegram User ID** field and save.

---

## Editorial Workflow

```
Source channel post
        │
        ▼
  userbot ingests
        │
        ▼
  normalize job
  ├── duplicate? → auto-rejected (no action needed)
  ├── auto channel → published immediately (no editorial step)
  └── queue channel → draft card posted to editor supergroup
                            │
                   Review in Telegram or web queue
                            │
              ┌─────────────┼─────────────┐
           Approve        Reject       Schedule
              │              │              │
           published      rejected      published at
                         (terminal)    scheduled time
```

**Auto channels** publish immediately after normalisation. Posts from these channels do not appear in the queue for review.

**Queue channels** require editorial approval. Draft cards appear in the editor supergroup and in the web queue simultaneously.

---

## Editor Supergroup: Draft Cards

When a post from a queue channel is ingested, the bot posts a draft card to the editor supergroup.

### Card layout

```
[state badge]  [source channel label]
Post #<id> · Source msg #<source_message_id>
Tags: tag-a, tag-b
Media: <type> · <size>   (if any)

<normalized text preview, up to 900 characters>

Scheduled: <UTC datetime>   (if scheduled)
```

### Inline buttons

| Button | Effect |
|---|---|
| ✅ Approve | Enqueues a publish job immediately. Post moves: `pending → approved → publishing → published`. |
| 🗑 Reject | Sets `state=rejected`. Irreversible from the bot — use the web UI if you need to recover a rejected post. |
| 🏷 Edit tags | Opens a link to the web UI for this post. From there you can change tags and view the full text before approving. |
| 🗓 Schedule | Opens a link to the web UI schedule picker for this post. |

**After publish:** the card is edited to display "☑️ Published ✓" with a single noop button. No further action is possible from the card.

**After reject:** the card is edited to display "🗑 REJECTED" and all buttons are removed.

### Button auth

Every button press is validated. The press is accepted only if:

- It comes from inside the configured editor supergroup (`EDITOR_GROUP_ID`).
- The Telegram user who pressed the button has a linked web account (`tg_user_id` set) with role `editor` or higher, and that account is not disabled.

If either condition fails, the press is silently ignored.

---

## Web Queue

The web queue at **/queue** shows all posts across all states.

### Filtering

Use the state filter to show only posts in a given state:

`pending` · `approved` · `scheduled` · `publishing` · `published` · `rejected` · `publish_failed`

### Pagination

The queue loads 50 posts per page. Click **Load More** to fetch the next 50.

### Per-card actions

| Action | Who | Notes |
|---|---|---|
| **Approve** | editor+ | Optionally select or change tags before confirming. Enqueues publish immediately. |
| **Reject** | editor+ | Sets `state=rejected`. |
| **Schedule** | editor+ | Pick a future UTC datetime with the datetime picker. Post moves to `scheduled`. |
| **Edit tags** | editor+ | Tag selection available inline on the card. |

---

## Tags

Tags are managed at **/tags** (admin+ only).

Each tag has:

- **Slug** — unique identifier used internally (e.g. `breaking-news`).
- **Label** — display name shown in the UI and on draft cards (e.g. `Breaking News`).
- **Color** — optional hex color for visual distinction in the UI.

### Assigning tags

- **During review** — select tags in the Approve dialog or via the Edit tags button.
- **Automatic defaults** — each source channel can have default tags. These are applied automatically during normalisation for auto channels, and pre-filled for queue channels. Defaults are configured on the source channel in the web back-office.

---

## Templates

Templates are managed at **/templates** (admin+ only) and assigned to source channels.

Templates are Jinja2 strings rendered during the `normalize` job to produce `normalized_text`.

### Available variables

| Variable | Content |
|---|---|
| `{{ text }}` | Raw message text from the source channel |
| `{{ source }}` | Source channel label |
| `{{ tags }}` | Comma-separated list of tag labels assigned to the post |

### Example

```jinja2
{{ source }} · {{ tags }}

{{ text }}
```

If no template is assigned to a source channel, a minimal default template is used (raw text only).

> **Note:** Changing a template does not affect duplicate detection. Deduplication is keyed on `raw_text` and media, not on `normalized_text`. Previously published content will not be re-published after a template change.

---

## Scheduled Posts

1. In the web queue, click **Schedule** on a post card.
2. Enter a future UTC datetime in the datetime picker.
3. Confirm. The post moves to `state=scheduled`.

At the scheduled time, ARQ fires a delayed publish job. The post then follows the normal publish flow: `scheduled → publishing → published`.

**If the worker was down** when the scheduled time passed: on next startup, `reconcile_scheduled` detects overdue scheduled posts (up to 30 days overdue) and re-enqueues their publish jobs automatically, in batches of 100.

---

## Publish Failures

If a publish job fails due to a Telegram error:

1. The post moves to `state=publish_failed`.
2. An alert is sent to the editor supergroup.
3. ARQ automatically retries the job with exponential backoff.

If ARQ retries are exhausted and the post remains in `publish_failed`, an operator must intervene. The current supported path is to set the post back to `approved` state in the database, which will allow a new publish job to be enqueued. A UI action for this is not yet exposed in the web back-office — flag this to the operator.

---

## Duplicate Detection

Posts with identical content are automatically rejected during normalisation. No manual action is required.

**How it works:**

A `dedupe_hash` is computed from the source message's raw text (whitespace-normalised, lowercased) and the media attachments (sorted by type and size). If a matching hash exists in `published_dedupe` within the last `DEDUPE_LOOKBACK_DAYS` (default: 7 days), the post is immediately set to `state=rejected` with `action=duplicate` and a `post_event` is recorded.

A secondary check runs at publish time as a race guard: if two concurrent normalize jobs produce the same hash and both pass the first check, only the first one to reach the publish step will succeed.

**What is not deduplicated:**

- Posts from the same source with different text or different media.
- Posts older than `DEDUPE_LOOKBACK_DAYS`.
- Posts where only the template changed (deduplication is on raw content, not rendered content).

---

## Source Channel Modes

Source channels are configured in the web back-office at **/channels** (admin+ only).

| Mode | Behaviour |
|---|---|
| **auto** | Posts are published immediately after normalisation. No draft card is created. |
| **queue** | Posts go to the editorial queue. A draft card is posted to the editor supergroup. |

Channels can be enabled or disabled. Disabled channels are excluded from the backfill and live listener on userbot startup.
