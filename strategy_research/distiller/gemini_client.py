"""Gemini API fallback distiller — used only when rule_extractor.py has low confidence,
or the input is a large raw corpus (long PDF, huge forum thread) where a big context
window is actually needed. Rate/quota-capped by the pipeline (research_pipeline in
config.yaml); callers must catch GeminiQuotaExceeded/GeminiNotConfigured and degrade
gracefully (skip that item) rather than let the pipeline crash — free-tier quotas are tight.
Requires GEMINI_API_KEY (Google AI Studio free tier) in .env. Output is raw, unvalidated
JSON: callers must pass each candidate through nl_to_rules.normalize_from_gemini.
"""
from __future__ import annotations

import json
import logging

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from config.settings import get_env

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are extracting structured trading-strategy rules from raw text.
Given the text below, identify at most 3 distinct, concrete trading strategy ideas. For
each, output JSON matching this schema exactly, as a JSON array (no prose, no markdown
fences):

[{{
  "name": "short strategy name",
  "archetype": "mean_reversion" | "momentum" | "pairs_trading" | "breakout",
  "entry_conditions": [{{"indicator": "RSI"|"MACD"|"BOLLINGER_UPPER"|"BOLLINGER_LOWER"|"KELTNER_UPPER"|"KELTNER_LOWER"|"ATR"|"VWAP"|"ZSCORE"|"SMA"|"EMA"|"VOLUME",
                          "operator": "<"|">"|"<="|">="|"crosses_above"|"crosses_below",
                          "threshold": number}}],
  "exit_conditions": [ ...same shape as entry_conditions... ],
  "timeframe": "e.g. 1m, 5m, 1d",
  "confidence": number between 0 and 1
}}]

For Bollinger Band rules, use BOLLINGER_LOWER for "price near/below the lower band"
(mean-reversion entries) and BOLLINGER_UPPER for "price near/above the upper band"
(mean-reversion exits, breakout entries) - there is no generic "BOLLINGER_BANDS" indicator.
For Keltner Channel rules (EMA +/- ATR multiple, distinct from Bollinger's standard
deviation bands), use KELTNER_UPPER/KELTNER_LOWER the same way.

If nothing in the text maps to a concrete, testable trading rule, return [].

TEXT:
{text}
"""


class GeminiNotConfigured(RuntimeError):
    """GEMINI_API_KEY is not set — caller should skip the Gemini fallback for this run."""


class GeminiQuotaExceeded(RuntimeError):
    """Free-tier rate/quota limit hit — caller should stop using the fallback this run."""


def _get_client():
    api_key = get_env("GEMINI_API_KEY")
    if not api_key:
        raise GeminiNotConfigured("GEMINI_API_KEY is not set in .env")
    from google import genai  # lazy import: optional dependency until configured

    return genai.Client(api_key=api_key)


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(GeminiQuotaExceeded),
)
def distill(text: str, model: str = "gemini-2.5-flash") -> list[dict]:
    """Returns a list of raw candidate dicts (unvalidated). Raises GeminiNotConfigured or
    GeminiQuotaExceeded for the caller (pipeline.py) to handle; any other provider error
    is logged and treated as "no candidates found" rather than propagated.
    """
    client = _get_client()
    try:
        response = client.models.generate_content(
            model=model,
            contents=EXTRACTION_PROMPT.format(text=text[:20000]),
        )
    except GeminiNotConfigured:
        raise
    except Exception as exc:
        if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
            raise GeminiQuotaExceeded(str(exc)) from exc
        logger.warning("Gemini distillation failed, skipping item: %s", exc)
        return []

    raw_text = (getattr(response, "text", "") or "").strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        candidates = json.loads(raw_text) if raw_text else []
    except json.JSONDecodeError:
        logger.warning("Gemini returned non-JSON output, skipping item")
        return []
    return candidates if isinstance(candidates, list) else []
