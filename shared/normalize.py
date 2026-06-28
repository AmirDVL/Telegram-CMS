"""Normalization: Jinja2 template rendering + tag-label resolution.

Shared by the normalize worker (renders the canonical text) and the aiogram bot
(renders draft-card previews with the same template).
"""

from __future__ import annotations

from jinja2 import StrictUndefined, select_autoescape
from jinja2.sandbox import ImmutableSandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Tag

# The single source of truth for the default normalization template. Used both as
# the worker's fallback (when a channel has no template bound) and as the body
# of the "Default" template seeded by the CLI — keeping them identical prevents
# drift between channels with/without a bound template.
DEFAULT_TEMPLATE_BODY = (
    "{% if tags %}{{ tags }}\n{% endif %}"
    "{{ text }}\n\n"
    "— {{ source_label }}"
)

_env = ImmutableSandboxedEnvironment(
    autoescape=select_autoescape(disabled_extensions=("jinja",)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_template(body: str, *, text: str, source_label: str, tags: str) -> str:
    """Render a normalization template.

    Recognized placeholders: ``{{ text }}``, ``{{ source_label }}``, ``{{ tags }}``.
    Missing values are coerced to empty strings so templates don't crash on posts
    that have no text/tags.
    """
    tmpl = _env.from_string(body)
    return tmpl.render(
        text=text or "",
        source_label=source_label or "",
        tags=tags or "",
    ).strip()


def format_tag_string(labels: list[str]) -> str:
    """Turn ['News','Tech'] -> '#news #tech'."""
    return " ".join(f"#{label.lower().replace(' ', '_')}" for label in labels if label)


async def resolve_tag_labels(session: AsyncSession, tag_ids: list[int]) -> list[str]:
    if not tag_ids:
        return []
    result = await session.execute(select(Tag.label).where(Tag.id.in_(tag_ids)))
    return [r[0] for r in result.all()]


async def normalize_text(
    session: AsyncSession,
    *,
    template_body: str,
    raw_text: str,
    source_label: str,
    tag_ids: list[int],
) -> str:
    labels = await resolve_tag_labels(session, tag_ids)
    return render_template(
        template_body,
        text=raw_text or "",
        source_label=source_label or "",
        tags=format_tag_string(labels),
    )
