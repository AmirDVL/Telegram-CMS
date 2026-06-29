"""AI transformation layer: translate / summarize / re-tone / custom prompt.

Toggle-controlled: only runs when ``ai_enabled=True`` on the channel (or tenant)
AND the global ``AI_ENABLED`` setting is ``True``.

Uses the **OpenAI-compatible** chat-completions API, which works with OpenAI,
Azure OpenAI, Ollama, vLLM, OpenRouter, and any other compatible endpoint.

Watermarking (tag stripping + brand append) is a pure text operation that never
calls the LLM — it runs regardless of the AI toggle when configured.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from shared.config import get_settings
from shared.enums import AIMode
from shared.logging import get_logger

log = get_logger("shared.transform")


class AITransformError(Exception):
    """Raised when the LLM API call fails (network, rate-limit, bad response)."""


# ── System-prompt builders ───────────────────────────────────────────────────

_TRANSLATE_SYSTEM = (
    "You are a professional translator. Translate the following message "
    "into {language}. Preserve the original formatting, line breaks, and "
    "any markdown/HTML tags. Do NOT add any commentary or explanation — "
    "return only the translated text."
)

_SUMMARIZE_SYSTEM = (
    "You are a professional editor. Summarize the following message into "
    "concise bullet points. Keep the key facts, strip opinion and filler. "
    "Use the same language as the original unless instructed otherwise. "
    "Return only the bullet-point summary, no preamble."
)

_RETONE_SYSTEM = (
    "You are a professional copywriter. Rewrite the following message to "
    "match this tone/style: {tone}. Preserve all factual information but "
    "adjust the language, formality, and voice accordingly. Return only "
    "the rewritten text."
)


def _build_system_prompt(
    mode: AIMode,
    *,
    target_language: str | None = None,
    tone_prompt: str | None = None,
    custom_system_prompt: str | None = None,
) -> str:
    if mode == AIMode.translate:
        lang = target_language or "Persian"
        return _TRANSLATE_SYSTEM.format(language=lang)
    if mode == AIMode.summarize:
        return _SUMMARIZE_SYSTEM
    if mode == AIMode.retone:
        tone = tone_prompt or "professional and concise"
        return _RETONE_SYSTEM.format(tone=tone)
    if mode == AIMode.custom:
        return custom_system_prompt or "You are a helpful assistant. Process the text below."
    return ""


# ── LLM API call ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class TransformResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


async def transform_text(
    raw_text: str,
    *,
    mode: AIMode,
    target_language: str | None = None,
    tone_prompt: str | None = None,
    custom_system_prompt: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> TransformResult:
    """Transform text using the configured LLM (OpenAI-compatible API).

    ``model``, ``max_tokens``, and ``timeout`` override the global settings when
    provided (used for per-tenant config overrides via ``shared.tenant.effective``).
    Pass ``None`` to fall back to the global ``Settings`` values.

    Raises ``AITransformError`` on any failure — the caller decides whether to
    fall back to the un-transformed text.
    """
    if mode == AIMode.off:
        return TransformResult(
            text=raw_text, model="none", prompt_tokens=0, completion_tokens=0, latency_ms=0
        )

    settings = get_settings()
    if not settings.ai_api_key:
        raise AITransformError("AI_API_KEY is not configured")

    system_prompt = _build_system_prompt(
        mode,
        target_language=target_language,
        tone_prompt=tone_prompt,
        custom_system_prompt=custom_system_prompt,
    )
    effective_model = model or settings.ai_model
    effective_max_tokens = max_tokens if max_tokens is not None else settings.ai_max_tokens
    effective_timeout = timeout if timeout is not None else settings.ai_timeout_seconds

    # Late import: the openai package is only required when AI is actually used.
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise AITransformError(
            "The 'openai' package is required for AI transformations. "
            "Install it with: pip install openai>=1.30.0"
        ) from exc

    client = AsyncOpenAI(
        api_key=settings.ai_api_key,
        base_url=settings.ai_provider_url,
        timeout=effective_timeout,
    )

    t0 = time.monotonic()
    try:
        response = await client.chat.completions.create(
            model=effective_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
            max_tokens=effective_max_tokens,
            temperature=0.3,
        )
    except Exception as exc:
        raise AITransformError(f"LLM API call failed: {exc}") from exc
    latency_ms = int((time.monotonic() - t0) * 1000)

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message.content:
        raise AITransformError("LLM returned an empty response")

    usage = response.usage
    return TransformResult(
        text=choice.message.content.strip(),
        model=response.model or effective_model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        latency_ms=latency_ms,
    )


# ── Watermark / branding ─────────────────────────────────────────────────────

# Common Telegram tag patterns: #tag, @username, t.me/channel links.
_TAG_PATTERNS = [
    re.compile(r"#\w+", re.UNICODE),  # #hashtag
    re.compile(r"@\w+", re.UNICODE),  # @username
    re.compile(r"https?://t\.me/\S+"),  # t.me links
]


def apply_watermark(
    text: str,
    *,
    watermark_text: str | None = None,
    strip_source_tags: bool = False,
) -> str:
    """Strip original channel tags and/or append branding watermark.

    This is a **pure text operation** — no LLM involved. It runs independently
    of the AI toggle and can be used on its own.
    """
    result = text

    if strip_source_tags:
        for pattern in _TAG_PATTERNS:
            result = pattern.sub("", result)
        # Clean up leftover whitespace from stripped tags.
        result = re.sub(r"\n{3,}", "\n\n", result).strip()

    if watermark_text:
        result = result.rstrip() + "\n\n" + watermark_text

    return result
