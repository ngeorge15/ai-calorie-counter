"""Shared HTTP setup for outbound nutrition APIs.

Two concerns, one library. pyrate-limiter backs both paths:

  USDA  we own the session, so requests-ratelimiter's LimiterSession applies
        the budget transparently on every call.
  OFF   the official SDK builds its own session and exposes no hook, so we
        guard the call site with a bare pyrate-limiter bucket instead.

Retries cover transient network faults only. 4xx is never retried — a barcode
that doesn't exist won't start existing on the third attempt.
"""
import os

from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate
from requests.adapters import HTTPAdapter
from requests_ratelimiter import LimiterSession
from urllib3.util.retry import Retry

TIMEOUT_SECONDS = 8

_RETRY = Retry(
    total=3,
    backoff_factor=0.4,          # 0.4s, 0.8s, 1.6s
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)


def _with_retries(session):
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# USDA FoodData Central: 1000 req/hour on a free data.gov key.
usda_session = _with_retries(LimiterSession(per_hour=1000))

# Open Food Facts: 15 req/min/IP. Raising rather than blocking keeps a burst
# from pinning a Render worker — we'd rather return 429 and let the phone fall
# back to its cache or to manual entry.
_off_limiter = Limiter(InMemoryBucket([Rate(15, Duration.MINUTE)]))


class RateLimited(Exception):
    """Our own budget is spent. Never let the upstream be the one to say no."""


def acquire_off_slot():
    """Reserve one OFF request, or raise. Non-blocking by choice.

    pyrate-limiter v4 returns a bool here rather than raising as v3 did, so the
    check is explicit. blocking=False means a burst fails fast instead of
    parking a Render worker for up to a minute.
    """
    if not _off_limiter.try_acquire("off", blocking=False):
        raise RateLimited("Open Food Facts budget exhausted")


def off_user_agent() -> str:
    # OFF blocks unidentified clients; this is a hard requirement, not etiquette.
    return os.environ.get(
        "OFF_USER_AGENT", "CalorieCounter/1.0 (contact-unset)"
    )
