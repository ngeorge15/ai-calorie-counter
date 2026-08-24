"""Timestamp parsing shared by the sync layer.

Everything crossing the wire is ISO8601 UTC. Everything in Mongo is a
timezone-aware datetime. Converting at exactly one boundary keeps the
clock-domain rule enforceable: see routes/meals.py for why that matters.
"""
import datetime as dt


def parse_iso(value):
    """Parse an ISO8601 string to an aware UTC datetime, or None."""
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def to_iso(value):
    if isinstance(value, dt.datetime):
        if not value.tzinfo:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).isoformat()
    return value


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def floor_ms(value: dt.datetime) -> dt.datetime:
    """Truncate to millisecond precision, matching BSON's storage granularity.

    MongoDB stores datetimes as milliseconds since epoch, so a value written
    at .638389 reads back as .638000. A sync cursor kept at microsecond
    precision would therefore sit *ahead* of rows written just after it, and
    those rows would never be returned — the same silent skip the two-clock
    design exists to prevent, reintroduced by the storage layer.

    Flooring the cursor to the same granularity, and pulling with $gte rather
    than $gt, makes the boundary overlap instead of gap. A row can be
    delivered twice; it can never be missed. Re-delivery is free because the
    client applies changes by client_id upsert.
    """
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)
