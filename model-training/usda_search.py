"""USDA FoodData Central text search + fuzzy food-name matching.

Split out from eval_real_photos.py so the matching heuristic and rate
limiter are unit-testable without a checkpoint, a model, or network access.

Auth/env pattern is copied from backend/app/usda_client.py (an
USDA_API_KEY env var, checked with is_configured() so the caller fails
loudly instead of guessing) rather than invented fresh. The retry policy
mirrors backend/app/net.py's _RETRY (429/5xx only, exponential backoff,
never retry a 4xx that means "this food doesn't exist"), and the 1000/hour
budget comes from the same requests-ratelimiter LimiterSession the backend
uses rather than a hand-rolled bucket.
"""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher

import requests
from requests.adapters import HTTPAdapter
from requests_ratelimiter import LimiterSession
from urllib3.util.retry import Retry

SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
TIMEOUT_SECONDS = 8

_RETRY = Retry(
    total=3,
    backoff_factor=0.4,  # 0.4s, 0.8s, 1.6s — same schedule as backend/app/net.py
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)


def is_configured() -> bool:
    """Same check as backend/app/usda_client.py — a missing key is a hard
    stop, not a reason to silently skip the USDA step."""
    return bool(os.environ.get("USDA_API_KEY"))


def require_api_key() -> str:
    key = os.environ.get("USDA_API_KEY")
    if not key:
        raise RuntimeError(
            "USDA_API_KEY is not set. The real-photo eval measures the "
            "classifier -> USDA search pipeline end to end, so it cannot "
            "run without hitting the real API. Get a free key (no card) at "
            "https://fdc.nal.usda.gov/api-key-signup and export it, e.g.\n"
            "  export USDA_API_KEY=your-key-here\n"
            "or set --skip-usda to compute classifier-only accuracy "
            "(no end-to-end number will be produced)."
        )
    return key


def build_session() -> requests.Session:
    """Same construction as backend/app/net.py's usda_session: a
    LimiterSession carrying USDA's 1000/hour free-key budget, with the
    retry policy mounted on top. The budget is enforced by the session
    itself, so no call site can forget to acquire a slot first.
    """
    session = LimiterSession(per_hour=1000)
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def search_food(
    session: requests.Session,
    query: str,
    api_key: str,
    page_size: int = 5,
    data_types: list[str] | None = None,
) -> list[dict]:
    """Free-text search against FDC. Returns a trimmed list of candidate
    foods (description, fdcId, dataType, brandName if present) — not the
    raw response, so callers don't need to know FDC's response shape.
    """
    params = {
        "query": query,
        "pageSize": page_size,
        "api_key": api_key,
    }
    if data_types:
        params["dataType"] = data_types

    response = session.get(SEARCH_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    candidates = []
    for food in response.json().get("foods", []):
        candidates.append({
            "fdcId": food.get("fdcId"),
            "description": food.get("description", ""),
            "dataType": food.get("dataType"),
            "brandName": food.get("brandName") or food.get("brandOwner"),
        })
    return candidates


_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def food_match(ground_truth: str, candidate_description: str, ratio_threshold: float = 0.6) -> bool:
    """Heuristic only — flags likely matches for triage, does not replace
    eyeballing the per-photo breakdown before quoting a success rate.

    Three cheap signals, any one of which is enough:
      1. one normalized string contains the other (handles "pizza" inside
         "cheese pizza, restaurant-prepared, FNDDS")
      2. token overlap: most of the ground-truth's words show up in the
         candidate
      3. difflib ratio, to catch close-but-not-substring matches
    """
    gt = normalize_text(ground_truth)
    cand = normalize_text(candidate_description)
    if not gt or not cand:
        return False

    if gt in cand or cand in gt:
        return True

    gt_tokens = set(gt.split())
    cand_tokens = set(cand.split())
    if gt_tokens and len(gt_tokens & cand_tokens) / len(gt_tokens) >= ratio_threshold:
        return True

    return SequenceMatcher(None, gt, cand).ratio() >= ratio_threshold
