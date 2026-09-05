"""Inbound rate limiting for the auth endpoints.

net.py already rate-limits OUTBOUND calls (USDA, Open Food Facts) with
pyrate-limiter. This module guards INBOUND traffic to /api/auth/* instead,
where the threat is different: a stranger hammering /login or /register on a
publicly reachable deployment, not us overrunning someone else's budget.

flask-limiter, not another pyrate-limiter bucket like _off_limiter in net.py:
  - It's the standard, well-maintained choice for rate-limiting a Flask
    *app's own* routes (per-route decorators, key funcs, retry-after headers,
    a Flask-native 429 flow) — pyrate-limiter is a general-purpose limiter we
    already reach for at outbound call sites, but reusing it here would mean
    hand-rolling the per-IP bucketing, decorator wiring, and header handling
    that flask-limiter already provides and maintains.
  - Reimplementing that on top of the lower-level primitive is exactly the
    kind of hand-rolled infra this project avoids when a maintained library
    already fits.

Storage: in-memory (flask-limiter's default), not Mongo. This carries the
*same* caveat as the OFF bucket in net.py and is deliberate for the same
reason — see render.yaml's `--workers 1` comment. In-memory counters live
per-process, so with more than one worker each process would enforce the
limit independently and the effective ceiling multiplies by worker count.
That's fine at 1 worker (Render's free-tier command in render.yaml) but it
is the same tripwire: move to a shared store (e.g. Mongo, or Redis if one
ever gets added) before scaling workers past one.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# storage_uri is explicit (not left to flask-limiter's default) so the choice
# reads as deliberate here rather than an oversight — same spirit as the
# --workers 1 comment in render.yaml this docstring points back to.
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
